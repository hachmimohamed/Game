from flask import Flask, render_template, jsonify, request
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, ContextTypes # <-- Correction: Import de ContextTypes
from telegram import Update

import os, threading, sqlite3, requests # <-- Correction: Décommenté les imports essentiels
# asyncio n'est pas nécessaire, mais peut être ajouté si besoin

# -------------------- CONFIGURATION --------------------
load_dotenv()  # Charge automatiquement le fichier .env

TELEGRAM_API_KEY = os.getenv("TELEGRAM_API_KEY")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
DB_PATH = "taptoearn.db"

app = Flask(__name__, template_folder="templates")

# -------------------- BASE DE DONNÉES --------------------
def get_db():
    """Ouvre une connexion SQLite."""
    # check_same_thread=False est nécessaire car Flask (dev) et le bot tournent dans des threads différents
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Crée la table si elle n’existe pas."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS players (
            chat_id TEXT PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0,
            per_click REAL DEFAULT 1,
            referrer TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# -------------------- ROUTES FLASK --------------------

@app.route("/")
def index():
    """Renvoie le fichier HTML du jeu."""
    return render_template("index.html")

@app.route("/api/state")
def state():
    """Renvoie les statistiques globales (balance, per_click)."""
    conn = get_db()
    row = conn.execute("SELECT SUM(balance) as balance, AVG(per_click) as per_click FROM players").fetchone()
    conn.close()
    return jsonify({
        "balance": row["balance"] or 0,
        "per_click": row["per_click"] or 1
    })

@app.route("/api/click", methods=["POST"])
def click():
    """Ajoute 1 coin globalement dans la base."""
    conn = get_db()
    # L'implémentation actuelle ajoute 1 coin à TOUS les joueurs.
    conn.execute("UPDATE players SET balance = balance + 1")
    conn.commit()
    row = conn.execute("SELECT SUM(balance) as balance FROM players").fetchone()
    conn.close()
    return jsonify({"balance": row["balance"] or 0})

# -------------------- BOT TELEGRAM --------------------
# Note: J'ai ajouté le type hint ContextTypes.DEFAULT_TYPE pour les bonnes pratiques
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /start - enregistre le joueur et envoie son lien."""
    chat_id = str(update.message.chat.id)
    username = update.message.from_user.username or "Anonyme"
    referrer = context.args[0] if context.args else None

    conn = get_db()
    conn.execute("""
        INSERT OR IGNORE INTO players (chat_id, username, balance, per_click, referrer)
        VALUES (?, ?, 0, 1, ?)
    """, (chat_id, username, referrer))
    
    # Bonus de parrainage
    if referrer and referrer != chat_id:
        conn.execute("UPDATE players SET balance = balance + 50 WHERE chat_id = ?", (referrer,))
    
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"👋 Bienvenue {username} !\n"
        f"Ton lien de jeu : http://127.0.0.1:5000/?ref={chat_id}\n"
        f"💰 Clique dans le jeu pour miner et gagner des coins !"
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /balance - affiche le solde du joueur."""
    chat_id = str(update.message.chat.id)
    conn = get_db()
    row = conn.execute("SELECT balance FROM players WHERE chat_id = ?", (chat_id,)).fetchone()
    conn.close()
    if row:
        await update.message.reply_text(f"💰 Ton solde actuel : {row['balance']:.0f} coins")
    else:
        await update.message.reply_text("Tu n’es pas encore enregistré. Envoie /start pour commencer.")

async def broadcast_message(text: str):
    """Envoie un message à tous les joueurs (utile pour test)."""
    conn = get_db()
    players = conn.execute("SELECT chat_id FROM players").fetchall()
    conn.close()
    if not TELEGRAM_API_KEY:
        print("⚠️ Pas de clé API Telegram !")
        return
    for p in players:
        chat_id = p["chat_id"]
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_API_KEY}/sendMessage",
                          json={"chat_id": chat_id, "text": text})
        except Exception as e:
            print("Erreur broadcast:", e)

def run_telegram_bot():
    """Lance le bot Telegram dans un thread séparé."""
    if not TELEGRAM_API_KEY:
        print("❌ Erreur : aucune clé TELEGRAM_API_KEY trouvée dans .env")
        return
    app_telegram = Application.builder().token(TELEGRAM_API_KEY).build()
    app_telegram.add_handler(CommandHandler("start", start))
    app_telegram.add_handler(CommandHandler("balance", balance))
    print("🤖 Bot Telegram en ligne… (utilise /start dans Telegram)")
    app_telegram.run_polling()

# -------------------- MAIN --------------------
if __name__ == "__main__":
    print("🚀 Démarrage du serveur Flask et du bot Telegram...")
    threading.Thread(target=run_telegram_bot, daemon=True).start()
    app.run(debug=True, port=5000)
)