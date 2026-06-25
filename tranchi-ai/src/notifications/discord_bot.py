"""
Hola AI Discord Bot — live chat interface for Big Moe Shafy.

Commands:
  !deals    — show latest approved deals from Supabase
  !status   — pipeline stats (pending / approved / rejected)
  !run      — trigger the full deal pipeline now
  @HolaAI   — ask anything in natural language

Approval flow:
  Bot posts ✅/❌ react prompts for each approved deal.
  React ✅ to send to buyers, ❌ to skip.

Set DISCORD_BOT_TOKEN in Railway Variables to enable.
"""

import os
import asyncio
import threading
import discord
from discord.ext import commands
from datetime import date

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# message_id → property_id for pending approval reactions
_pending = {}


def _sb():
    from config import SUPABASE_URL, SUPABASE_KEY
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)


@bot.event
async def on_ready():
    print(f"[DISCORD BOT] Online as {bot.user}", flush=True)


# ── !deals ──────────────────────────────────────────────
@bot.command(name="deals")
async def deals_cmd(ctx):
    try:
        rows = _sb().table("auction_properties") \
            .select("address,city,state,ai_grade,mao,estimated_arv,net_profit_estimate") \
            .eq("ai_status", "APPROVE") \
            .order("created_at", desc=True) \
            .limit(8) \
            .execute().data or []

        if not rows:
            await ctx.send("No approved deals yet. Use `!run` to start the pipeline.")
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
        await ctx.send("\n".join(lines))
    except Exception as e:
        await ctx.send(f"⚠️ {e}")


# ── !status ─────────────────────────────────────────────
@bot.command(name="status")
async def status_cmd(ctx):
    try:
        rows = _sb().table("auction_properties").select("ai_status").execute().data or []
        counts: dict[str, int] = {}
        for r in rows:
            s = r.get("ai_status", "UNKNOWN")
            counts[s] = counts.get(s, 0) + 1

        await ctx.send(
            f"**📊 Pipeline Status — {date.today()}**\n"
            f"✅ Approved: **{counts.get('APPROVE', 0)}**\n"
            f"⏳ Pending:  **{counts.get('PENDING', 0)}**\n"
            f"❌ Rejected: **{counts.get('REJECT', 0)}**\n"
            f"🔍 Review:   **{counts.get('REVIEW', 0)}**"
        )
    except Exception as e:
        await ctx.send(f"⚠️ {e}")


# ── !run ────────────────────────────────────────────────
@bot.command(name="run")
async def run_cmd(ctx):
    import subprocess, sys as _sys
    app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    subprocess.Popen([_sys.executable, "main.py", "all"], cwd=app_dir)
    await ctx.send("🚀 Pipeline started — deal cards will appear here as properties get approved.")


# ── !help ───────────────────────────────────────────────
@bot.command(name="help")
async def help_cmd(ctx):
    await ctx.send(
        "**Hola AI Commands**\n"
        "`!deals`  — show latest approved deals\n"
        "`!status` — pipeline stats\n"
        "`!run`    — trigger the deal pipeline now\n"
        "`@HolaAI <question>` — ask me anything"
    )


# ── @mention → natural language chat ─────────────────────
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    if bot.user in message.mentions:
        question = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if not question:
            await message.reply("What's up? Ask me about deals, pipeline status, or anything Hola AI related.")
            return

        async with message.channel.typing():
            try:
                from src.utils.free_llm import call_llm
                system = (
                    "You are Hola AI assistant for Big Moe Shafy, a real estate wholesale investor. "
                    "You manage an automated pipeline that scrapes government auction properties, "
                    "AI-underwrites them with the 70% rule, and connects them with cash buyers. "
                    "Be concise and direct. For deal data suggest !deals or !status commands. "
                    f"Today is {date.today()}."
                )
                reply = call_llm(system, question, max_tokens=400)
                await message.reply(reply[:1900])
            except Exception as e:
                await message.reply(f"⚠️ {e}")


# ── Reaction handler for deal approvals ────────────────────
@bot.event
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
            await reaction.message.channel.send(f"✅ Deal approved — queued for buyer outreach.")
        except Exception as e:
            await reaction.message.channel.send(f"⚠️ Approval error: {e}")
    elif str(reaction.emoji) == "❌":
        await reaction.message.channel.send(f"❌ Deal skipped.")

    del _pending[reaction.message.id]


# ── Entry point ─────────────────────────────────────────────

def run_bot():
    if not BOT_TOKEN:
        print("[DISCORD BOT] DISCORD_BOT_TOKEN not set — bot disabled", flush=True)
        return
    try:
        asyncio.run(bot.start(BOT_TOKEN))
    except Exception as e:
        print(f"[DISCORD BOT] Error: {e}", flush=True)
