from pathlib import Path
import json
import os
import asyncio
import discord

# Metadata
UniqueID = os.getenv('UniqueID')
HintDirectory = os.getcwd() + os.getenv('HintDirectory') + UniqueID + '/'
HintLogLocation = HintDirectory + 'PendingHints.txt'
HintPingRegister = HintDirectory + 'RegisteredGames.csv'

# =========================
# CONFIG / PERSISTENCE
# =========================

class ReactionConfig:
    def __init__(self):
        import os
        base_path = Path(HintDirectory)
        filename = os.getenv("ReactionMessageConfig", "reaction_messages.json")
        self.path = base_path / filename

        self.data = {"messages": []}
        self.load()

    def load(self):
        if not self.path.exists():
            self.save()
            return

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            self.data = {"messages": []}
            self.save()

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def add_message(self, message_id, slots, emojis):
        self.data["messages"].append({
            "message_id": message_id,
            "slots": slots,
            "emojis": emojis
        })
        self.save()

    def get_all_messages(self):
        return self.data["messages"]

    def get_slot_by_reaction(self, message_id, emoji):
        for msg in self.data["messages"]:
            if msg["message_id"] == message_id:
                if emoji in msg["emojis"]:
                    idx = msg["emojis"].index(emoji)
                    return msg["slots"][idx]
        return None

    def is_managed_message(self, message_id):
        return any(msg["message_id"] == message_id for msg in self.data["messages"])


# =========================
# CONSTANTS
# =========================

EMOJIS = [
    "0️⃣","1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣",
    "🇦","🇧","🇨","🇩","🇪"
]

CHUNK_SIZE = 15


# =========================
# MESSAGE CREATION
# =========================

async def create_reaction_messages(bot, channel, slots, config):
    slots = sorted(slots, key=lambda x: x.lower())
    chunks = [slots[i:i+CHUNK_SIZE] for i in range(0, len(slots), CHUNK_SIZE)]

    for chunk in chunks:
        emojis = EMOJIS[:len(chunk)]

        lines = [
            "**Slot Subscription**",
            "React to receive pings when a hint for your slot is received/resolved:\n"
        ]

        for i, slot in enumerate(chunk):
            lines.append(f"{emojis[i]} {slot}")

        message = await channel.send("\n".join(lines))

        for emoji in emojis:
            await message.add_reaction(emoji)
            await asyncio.sleep(0.2)

        config.add_message(message.id, chunk, emojis)


# =========================
# CSV (REGISTERED GAMES)
# =========================

def get_csv_path():
    return Path(HintPingRegister)


def load_csv():
    path = get_csv_path()
    data = {}

    if not path.exists():
        return data

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) >= 2:
                slot = parts[0]
                type_ = int(parts[1])

                if type_ == 0:
                    users = parts[2:] if len(parts) > 2 else []
                    data[slot] = {"type": 0, "users": users}
                else:
                    role_id = parts[2] if len(parts) > 2 else None
                    data[slot] = {"type": 1, "role": role_id}

    return data


def save_csv(data):
    path = get_csv_path()

    with open(path, "w", encoding="utf-8") as f:
        for slot, info in data.items():
            if info["type"] == 0:
                users = ",".join(info.get("users", []))
                line = f"{slot},0"
                if users:
                    line += f",{users}"
            else:
                role = info.get("role", "")
                line = f"{slot},1,{role}"

            f.write(line + "\n")


# =========================
# MESSAGE UPDATE
# =========================

async def update_reaction_message(bot, message_id, slots, emojis):
    channel_id = int(os.getenv("DiscordReactionChannel"))
    channel = bot.get_channel(channel_id)

    try:
        message = await channel.fetch_message(message_id)
    except:
        return

    data = load_csv()

    lines = [
            "**Slot Subscription**",
            "React to receive pings when a hint for your slot is received/resolved:\n"
    ]

    for i, slot in enumerate(slots):
        line = f"{emojis[i]} {slot}"

        if slot in data:
            info = data[slot]

            # INDIVIDUAL (Slot behind players)
            if info["type"] == 0:
                users = info.get("users", [])
                if users:
                    mentions = [f"<@{uid}>" for uid in users]
                    line += " => " + ", ".join(mentions)

            # GROUP (Slot behind role)
            else:
                role_id = info["role"]
                if role_id:
                    line += f" => <@&{role_id}>"

        lines.append(line)

    await message.edit(content="\n".join(lines))


# =========================
# REACTION HANDLERS
# =========================

async def handle_reaction_add(bot, payload, config):
    print("REACTION ADD DETECTED:", payload.emoji)

    if payload.user_id == bot.user.id:
        return

    if not config.is_managed_message(payload.message_id):
        return

    emoji = str(payload.emoji)
    slot = config.get_slot_by_reaction(payload.message_id, emoji)

    if not slot:
        return

    guild = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id)

    data = load_csv()

    if slot not in data:
        return

    info = data[slot]

    if info["type"] == 0:
        users = info.get("users", [])
        if str(member.id) not in users:
            users.append(str(member.id))
            info["users"] = users
    else:
        role_id = int(info["role"])
        role = guild.get_role(role_id)
        if role:
            await member.add_roles(role)

    save_csv(data)

    for msg in config.get_all_messages():
        if msg["message_id"] == payload.message_id:
            await update_reaction_message(bot, msg["message_id"], msg["slots"], msg["emojis"])


async def handle_reaction_remove(bot, payload, config):
    print("REACTION REMOVE DETECTED:", payload.emoji)

    if payload.user_id == bot.user.id:
        return

    if not config.is_managed_message(payload.message_id):
        return

    emoji = str(payload.emoji)
    slot = config.get_slot_by_reaction(payload.message_id, emoji)

    if not slot:
        return

    guild = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id)

    data = load_csv()

    if slot not in data:
        return

    info = data[slot]

    if info["type"] == 0:
        users = info.get("users", [])
        if str(member.id) in users:
            users.remove(str(member.id))
            info["users"] = users
    else:
        role_id = int(info["role"])
        role = guild.get_role(role_id)
        if role:
            await member.remove_roles(role)

    save_csv(data)

    for msg in config.get_all_messages():
        if msg["message_id"] == payload.message_id:
            await update_reaction_message(bot, msg["message_id"], msg["slots"], msg["emojis"])


# =========================
# MAIN SETUP
# =========================

async def setup_reaction_system(bot, slots):
    slots = sorted(slots, key=lambda x: x.lower())
    if os.getenv("ReactionPingRegister", "false").lower() != "true":
        return None

    print("[ReactionSystem] Starting...")

    channel_id = int(os.getenv("DiscordReactionChannel"))
    channel = bot.get_channel(channel_id)

    if not channel:
        print("[ReactionSystem] Channel not found")
        return None

    config = ReactionConfig()
    csv_path = get_csv_path()

    if not csv_path.exists() or os.stat(csv_path).st_size == 0:
        print("[ReactionSystem] Initial setup required")

        msg_lines = [
            "**Configure group slots**",
            "Reply with:\n`number @role` per line\n"
            ]

        for i, slot in enumerate(slots):
            msg_lines.append(f"{i+1}. {slot}")

        await channel.send("\n".join(msg_lines))

        def check(m):
            return m.channel.id == channel.id and not m.author.bot

        try:
            reply = await bot.wait_for("message", timeout=120, check=check)
        except asyncio.TimeoutError:
            return None

        group_map = {}

        for line in reply.content.splitlines():
            try:
                num, role = line.split()
                index = int(num) - 1
                role_id = role.replace("<@&", "").replace(">", "")
                group_map[slots[index]] = role_id
            except:
                continue

        data = {}
        for slot in slots:
            if slot in group_map:
                data[slot] = {"type": 1, "role": group_map[slot]}
            else:
                data[slot] = {"type": 0, "users": []}

        save_csv(data)
        await channel.send("Configuration completed ✅")

    if not config.get_all_messages():
        print("[ReactionSystem] Creating messages...")
        await create_reaction_messages(bot, channel, slots, config)
    else:
        print("[ReactionSystem] Using existing messages")

    return config