"""
Hola AI Discord Bot — live chat interface for Big Moe Shafy.

Uses SLASH COMMANDS so it needs NO privileged intents — connects the
moment a valid DISCORD_BOT_TOKEN is set, with zero Developer Portal changes.

Slash commands:
  /status   — pipeline stats (pending / approved / rejected)
  /deals    — show latest approved deals from Supabase
  /run      — trigger the full deal pipeline now
  /ask      — ask anything in natural language

Approval flow:
  Bot posts ✅/❌ react prompts for each approved deal.
  React ✅ to send to buyers, ❌ to skip.

Set DISCORD_BOT_TOKEN in Railway Variables to enable.
"""

import os
import asyncio
import discord
from discord import app_commands
from datetime import date

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# Default intents only — NO privileged intents (message_content/members).
# Slash commands and reactions both work without them, so the bot connects
# without any Discord Developer Portal toggles.
intents = discord.Intents.default()

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# message_id → property_id for pending approval reactions
_pending = {}


def _sb():
    from config import SUPABASE_URL, SUPABASE_KEY
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)


@client.event
async def on_ready():
    # Sync commands to every guild the bot is in — guild syncs are INSTANT,
    # unlike global syncs which can take up to an hour to appear.
    try:
        for guild in client.guilds:
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)
            print(f"[DISCORD BOT] synced commands to guild: {guild.name} ({guild.id})", flush=True)
        # Also push a global sync as a fallback for any future guilds.
        await tree.sync()
        print(f"[DISCORD BOT] Online as {client.user} — slash commands ready", flush=True)
    except Exception as e:
        print(f"[DISCORD BOT] command sync error: {e}", flush=True)


# ── /status ───────────────────────────────────────────────────
@tree.command(name="status", description="Pipeline stats (approved / pending / rejected)")
async def status_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        rows = _sb().table("auction_properties").select("ai_status").execute().data or []
        counts: dict[str, int] = {}
        for r in rows:
            s = r.get("ai_status", "UNKNOWN")
            counts[s] = counts.get(s, 0) + 1

        await interaction.followup.send(
            f"**📊 Pipeline Status — {date.today()}**\n"
            f"✅ Approved: **{counts.get('APPROVE', 0)}**\n"
            f"⏳ Pending:  **{counts.get('PENDING', 0)}**\n"
            f"❌ Rejected: **{counts.get('REJECT', 0)}**\n"
            f"🔍 Review:   **{counts.get('REVIEW', 0)}**"
        )
    except Exception as e:
        await interaction.followup.send(f"⚠️ {e}")


# ── /deals ────────────────────────────────────────────────────
@tree.command(name="deals", description="Show the latest approved deals")
async def deals_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        rows = _sb().table("auction_properties") \
            .select("address,city,state,ai_grade,mao,estimated_arv,net_profit_estimate") \
            .eq("ai_status", "APPROVE") \
            .order("created_at", desc=True) \
            .limit(8) \
            .execute().data or []

        if not rows:
            await interaction.followup.send("No approved deals yet. Use `/run` to start the pipeline.")
            return

        lines = [f"**🏠 Top Approved Deals — {date.today()}**"]
        for p in rows:
            profit = p.get("net_profit_estimate") or 0
            mao    = p.get("mao") or 0
            lines.append(
                f"• **{p['address']}, {p.get('city','')} {p.get('state','')}** "
                f"| Grade: `{p.get('ai_grade','?')}` "
                f"| MAO: `${mao:,.0f}` "
                f"| Profit: `${profit:,.0f}`"
            )
        await interaction.followup.send("\n".join(lines))
    except Exception as e:
        await interaction.followup.send(f"⚠️ {e}")


# ── /run ──────────────────────────────────────────────────────
@tree.command(name="run", description="Trigger the full deal pipeline now")
async def run_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    import subprocess, sys as _sys
    app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    subprocess.Popen([_sys.executable, "main.py", "all"], cwd=app_dir)
    await interaction.followup.send("🚀 Pipeline started — deal cards will appear here as properties get approved.")


# ── /ask ──────────────────────────────────────────────────────
@tree.command(name="ask", description="Ask Hola AI anything")
@app_commands.describe(question="Your question")
async def ask_cmd(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    try:
        from src.utils.free_llm import call_llm
        system = (
            "You are Hola AI assistant for Big Moe Shafy, a real estate wholesale investor. "
            "You manage an automated pipeline that scrapes government auction properties, "
            "AI-underwrites them with the 70% rule, and connects them with cash buyers. "
            "Be concise and direct. For deal data suggest /deals or /status commands. "
            f"Today is {date.today()}."
        )
        reply = call_llm(system, question, max_tokens=400)
        await interaction.followup.send(reply[:1900])
    except Exception as e:
        await interaction.followup.send(f"⚠️ {e}")


# ── Reaction handler for deal approvals ──────────────────────
@client.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return
    prop_id = _pending.get(reaction.message.id)
    if not prop_id:
        return

    if str(reaction.emoji) == "✅":
        try:
            _sb().table("auction_properties") \
                .update({"status": "APPROVED"}) \
                .eq("id", prop_id) \
                .execute()
            await reaction.message.channel.send("✅ Deal approved — queued for buyer outreach.")
        except Exception as e:
            await reaction.message.channel.send(f"⚠️ Approval error: {e}")
    elif str(reaction.emoji) == "❌":
        await reaction.message.channel.send("❌ Deal skipped.")

    del _pending[reaction.message.id]


# ── Post approval prompt (called from pipeline) ──────────────
async def post_approval_prompt(channel_id: int, prop: dict, decision: dict) -> None:
    channel = client.get_channel(channel_id)
    if not channel:
        return
    grade  = decision.get("ai_grade", "?")
    profit = decision.get("net_profit_estimate", 0) or 0
    mao    = decision.get("mao", 0) or 0
    addr   = prop.get("address", "Unknown")
    msg = await channel.send(
        f"🏠 **Grade {grade} Deal — {addr}**\n"
        f"MAO: `${mao:,.0f}` | Est. Profit: `${profit:,.0f}`\n"
        f"React ✅ to send to buyers · ❌ to skip"
    )
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")
    _pending[msg.id] = prop.get("id")


# ── Entry point ───────────────────────────────────────────────
def run_bot():
    if not BOT_TOKEN:
        print("[DISCORD BOT] DISCORD_BOT_TOKEN not set — bot disabled", flush=True)
        return
    try:
        asyncio.run(client.start(BOT_TOKEN))
    except Exception as e:
        print(f"[DISCORD BOT] Error: {e}", flush=True)
