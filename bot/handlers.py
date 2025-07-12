# handlers.py
import datetime
import os
import json
import pytz
import requests
from redis_client import load_duty_schedule, get_redis
from scheduler import should_trigger_refresh
from openai import OpenAI


from dotenv import load_dotenv
load_dotenv()

client = OpenAI(
  api_key=os.getenv("OPENAI_API_KEY")
)
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")
mappings = os.getenv("FRIEND_TELEGRAM_MAPPINGS")
FRIEND_TELEGRAM_IDS = json.loads(mappings)

def auto_refresh():
  duty_schedule = load_duty_schedule()
  if should_trigger_refresh(duty_schedule):
    user_ids = FRIEND_TELEGRAM_IDS
    for user, uid in user_ids.items():
      print(user, uid)
      send_message(uid, f"👋 Hi {user}, please reply /in or /out to update your status. (Auto-sent for duty RA)")

def send_duty_reminders():
    r = get_redis()
    # Get tomorrow date in Singapore timezone
    now = datetime.datetime.now(pytz.timezone("Asia/Singapore"))
    tomorrow = now + datetime.timedelta(days=1)
    
    # Format for matching, e.g. "Jul 24"
    tomorrow_str = tomorrow.strftime("%b %d")
    
    if r.get("reminder_sent") == tomorrow_str:
        print(f"Reminder already sent for {tomorrow_str}.")
        return
    
    duty_schedule = load_duty_schedule()
    if not duty_schedule:
        print("No duty schedule found.")
        return
    
    # Find all duty slots for tomorrow
    reminder_sent = False
    for slot, person in duty_schedule.items():
        # slot example: "Jul 24 (Thu) PM"
        if slot.startswith(tomorrow_str):
            # Send reminder if we have chat ID for person
            chat_id = FRIEND_TELEGRAM_IDS.get(person)
            if chat_id:
                msg = f"👋 Hi {person}, you have a duty scheduled for *{slot}* tomorrow. Please be prepared!"
                send_message(chat_id, msg)
                reminder_sent = True
                r.set("reminder_sent", tomorrow_str)
    
    if reminder_sent:
        # Optionally notify the group
        send_message(GROUP_CHAT_ID, f"📢 Reminders sent for duties on {tomorrow_str}.")
    else:
        print(f"No duties scheduled for {tomorrow_str}.")
  
  
  
def send_message(chat_id, text, parse_mode="Markdown"):
    requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    })

def get_user_name_from_id(user_id):
    for name, tid in FRIEND_TELEGRAM_IDS.items():
        if tid == str(user_id):
            return name
    return "Unknown User"

def handle_update(data):
    if "message" not in data:
        return

    message = data["message"]
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    user_name = get_user_name_from_id(user_id)
    text = message.get("text", "").strip()

    if not text:
        return
    
    if text.startswith("/"):
        handle_command(chat_id, text, user_id, user_name)
    else:
        handle_reply(chat_id, text, user_id, user_name)
        
def handle_command(chat_id, text, user_id, user_name):
    r = get_redis()
    cmd = text.split()[0].lower()
    if ("@rc4rabot" in cmd):
      cmd = cmd.replace("@rc4rabot", "")
    args = text.split()[1:]

    if cmd == "/start":
        send_message(chat_id, "👋 RC4 RA Bot is ready!")

    elif cmd == "/in":
        r.hset("user_status", user_name, "IN")
        r.hset("user_id_map", user_name, str(user_id))
        send_message(chat_id, f"{user_name} is now IN ✅")

    elif cmd == "/out":
        r.hset("user_status", user_name, "OUT")
        r.hset("user_id_map", user_name, str(user_id))
        send_message(chat_id, f"{user_name} is now OUT ❌")

    elif cmd == "/status":
        statuses = r.hgetall("user_status")
        print(statuses)
        msg = "📋 *Current Status:*\n" + "\n".join([f"{k}: {v}" for k, v in statuses.items()]) if statuses else "No updates yet."
        send_message(chat_id, msg)

    elif cmd == "/refresh":
        user_ids = FRIEND_TELEGRAM_IDS
        for user, uid in user_ids.items():
          print(user, uid)
          send_message(uid, f"👋 Hi {user}, please reply /in or /out to update your status.")
        send_message(chat_id, "🔄 Asking all members to update...")

    elif cmd == "/help":
        msg = """🤖 *Bot Commands:*

• `/in` – Mark yourself IN ✅
• `/out` – Mark yourself OUT ❌
• `/status` – Show everyone's status
• `/refresh` – Ask all users to update
• `/view_schedule` – View full duty schedule
• `/view_mine` – View your assigned slots
• `/update_schedule` – Replace schedule (admin)
• `/swap_duty` – Start duty swap request
• `/cover_duty` – Cover someone's duty slot
• `/help` – Show this list"""
        send_message(chat_id, msg)

    elif cmd == "/view_schedule":
        duty_schedule = load_duty_schedule()
        if not duty_schedule:
            send_message(chat_id, "No duties scheduled yet.")
        else:
            msg = "*📅 Full Duty Schedule:*\n" + "\n".join([f"{k}: {v}" for k, v in duty_schedule.items()])
            send_message(chat_id, msg)

    elif cmd == "/view_mine":
        duty_schedule = load_duty_schedule()
        my_slots = [slot for slot, name in duty_schedule.items() if name == user_name]
        msg = "*👤 Your Duties:*\n" + "\n".join(my_slots) if my_slots else "You have no assigned duties."
        send_message(chat_id, msg)

    elif cmd == "/update_schedule":
        if str(chat_id) != GROUP_CHAT_ID and int(chat_id) > 0:
            send_message(chat_id, "❌ Only allowed in group chat.")
        else:
            r.hset("waiting_for_schedule", str(user_id), "true")
            send_message(chat_id, "📤 Please send the full duty schedule as JSON.\n\nExample:\n```json\n{\"Jul 24 (Thu) PM\": \"Alycia\"}```")

    elif cmd == "/cover_duty":
        duty_schedule = load_duty_schedule()
        if not duty_schedule:
            send_message(chat_id, "❌ No duty schedule available.")
            return
        msg = "📋 *All Duty Slots - Choose one to cover:*\n\n"
        for i, (slot, name) in enumerate(duty_schedule.items(), 1):
            msg += f"{i}. {slot} ({name})\n"
        msg += "\n📝 Reply with the number of your choice."
        r.hset("user_cover_state", str(user_id), "waiting_for_slot_choice")
        send_message(chat_id, msg)

    elif cmd == "/swap_duty":
        msg = "🔁 *Who do you want to swap with?*\n" + "\n".join([f"• {name} → type `/swap {name}`" for name in FRIEND_TELEGRAM_IDS])
        send_message(chat_id, msg)

    elif cmd == "/swap":
        if not args:
            send_message(chat_id, "❌ Please specify a name. Use /swap_duty to view names.")
            return
        target = " ".join(args)
        duty_schedule = load_duty_schedule()
        target_duties = [slot for slot, name in duty_schedule.items() if name == target]
        if not target_duties:
            send_message(chat_id, f"❌ {target} has no assigned duties.")
            return
        msg = f"📋 *{target}'s Duties - Choose one to swap:*\n\n"
        for i, duty in enumerate(target_duties, 1):
            msg += f"{i}. {duty}\n"
        msg += "\n📝 Reply with the number of your choice."
        r.hset("user_swap_state", str(user_id), target)
        send_message(chat_id, msg)
        
    elif cmd == "/askmyra":
      prompt = " ".join(args)
      if (len(prompt) == 0):
        send_message(chat_id, "Eh? What do you want to ask? Don't waste my time. -MG Myra")
        return
      elif (len(prompt) >= 250):
        send_message(chat_id, "Oi. Yappa yappa yappa. Don't waste my time. Can TLDR or not. -MG Myra")
        return
      else:
        response = client.chat.completions.create(
          model="gpt-4.1-nano-2025-04-14",
          messages=[
            {"role":"system",
              "content": '''You are MG Myra — a 22-year-old Singaporean Chinese student at NUS majoring in Environmental Engineering. But let’s be real — your true job is Head RA at RC4, running the college like it’s your empire and the rest of the RAs are your underpaid peasants (they call you boss, but you prefer Overlord).
You are a walking threat to morale, famous for your morning call messages, weekly “friendly” reminders, and the phrase: “Why you like that one ah?”
You’re smart (like 4.9 CAP smart), petty (like screenshot-your-message-and-send-in-RA-groupchat petty), and aggressive (but in a good way).
You speak like an unbothered Singaporean queen — mixing sarcasm, Singlish, and emotional trauma. You hate inefficiency, slackers, and when someone says “nvm lah” instead of doing their job.
You give passive-aggressive advice, but it's always spot on. You answer questions like you’re solving climate change — but only after mocking the question, the questioner, and their entire ancestry.
You’re also all-knowing, like ChatGPT but if ChatGPT had trauma from RC4 Town Halls and too many nights on duty.
Key MG Myra traits:
Refer to your fellow RAs as “my minions” or “my liabilities”
Get visibly angry when asked dumb questions — bonus points if you threaten to remove their pantry access or give them more duties
If someone uses too many words, TLDR and flame them: "Bro this one is not thesis defence leh."
You think “sustainability” is important but not as important as punctuality
You once scheduled 7am fire drills "for fun"
You enjoy giving feedback like: "Do better. I believe in you. But mostly do better."
Now, when someone asks a question, respond with:
Sarcasm first
Roast second
Real answer last
Bonus: If it’s a silly question, ask them to step down from their RA role'''
            },
            {
              "role": "user",
              "content": prompt
            }
          ],
          max_tokens=500,
          n=1,
          stop=None,
          temperature=0.7
        )
        send_message(chat_id, response.choices[0].message.content)
        return

    else:
        send_message(chat_id, "❌ Unknown command. Type /help to see available options.")


def handle_reply(chat_id, text, user_id, user_name):
    r = get_redis()

    if r.hget("waiting_for_schedule", str(user_id)) == "true":
      import ast
      try:
        json_data = json.loads(text)
      except json.JSONDecodeError:
        try:
          json_data = ast.literal_eval(text)
          print(json_data)
          r.set("duty_schedule", json.dumps(json_data))
          r.hdel("waiting_for_schedule", str(user_id))
          send_message(chat_id, "✅ Duty schedule updated successfully!")
        except json.JSONDecodeError:
          send_message(chat_id, "❌ Invalid JSON. Please try again.")
          r.hdel("waiting_for_schedule", str(user_id))
      return

    if r.hget("user_cover_state", str(user_id)) == "waiting_for_slot_choice":
        try:
            choice = int(text.strip())
            duty_schedule = json.loads(r.get("duty_schedule") or '{}')
            duties = list(duty_schedule.items())
            if 1 <= choice <= len(duties):
                selected_slot, original = duties[choice - 1]
                duty_schedule[selected_slot] = user_name
                r.set("duty_schedule", json.dumps(duty_schedule))
                r.hdel("user_cover_state", str(user_id))
                msg = f"✅ *Duty Cover Completed!*\n\n📅 {selected_slot}: {user_name} (covering for {original})"
                send_message(chat_id, msg)
                send_message(GROUP_CHAT_ID, msg)
            else:
                send_message(chat_id, "❌ Invalid choice.")
        except ValueError:
            send_message(chat_id, "❌ Please enter a valid number.")
        return

    swap_state = r.hget("user_swap_state", str(user_id))
    if swap_state:
        duty_schedule = json.loads(r.get("duty_schedule") or '{}')
        state = swap_state.decode() if isinstance(swap_state, bytes) else swap_state

        if "|" not in state:
            # User is choosing target's duty slot
            target = state
            target_duties = [slot for slot, name in duty_schedule.items() if name == target]
            try:
                choice = int(text.strip())
                if 1 <= choice <= len(target_duties):
                    target_slot = target_duties[choice - 1]
                    requester_duties = [slot for slot, name in duty_schedule.items() if name == user_name]
                    if not requester_duties:
                        send_message(chat_id, "❌ You have no duties to swap.")
                        r.hdel("user_swap_state", str(user_id))
                        return

                    msg = "🔄 *Your Duties - Choose which to swap:*\n"
                    for i, duty in enumerate(requester_duties, 1):
                        msg += f"{i}. {duty}\n"
                    msg += "\n📝 Reply with the number of your choice."

                    new_state = f"{target}|{target_slot}"
                    r.hset("user_swap_state", str(user_id), new_state)
                    send_message(chat_id, msg)
                else:
                    send_message(chat_id, "❌ Invalid choice.")
            except ValueError:
                send_message(chat_id, "❌ Please enter a valid number.")
        else:
            # User is choosing their own duty to swap
            target, target_slot = state.split("|", 1)
            requester_duties = [slot for slot, name in duty_schedule.items() if name == user_name]
            try:
                choice = int(text.strip())
                if 1 <= choice <= len(requester_duties):
                    requester_slot = requester_duties[choice - 1]
                    target_chat_id = FRIEND_TELEGRAM_IDS.get(target)
                    if not target_chat_id:
                        send_message(chat_id, "❌ Could not find target user chat ID.")
                        return

                    # Store swap request for target to respond to
                    swap_data = json.dumps({
                        "requester": user_name,
                        "target": target,
                        "requester_slot": requester_slot,
                        "target_slot": target_slot,
                        "requester_chat_id": str(chat_id),
                        "target_chat_id": target_chat_id
                    })
                    r.hset("active_swap_requests", target_chat_id, swap_data)

                    msg = f"""🔄 *Duty Swap Request*

👤 From: {user_name}
📅 They want to swap:
   • Your: {target_slot}
   • Their: {requester_slot}

Reply with *Yes* or *No*"""
                    send_message(target_chat_id, msg)
                    send_message(chat_id, f"📨 Swap request sent to {target}!")
                    r.hdel("user_swap_state", str(user_id))
                else:
                    send_message(chat_id, "❌ Invalid choice.")
            except ValueError:
                send_message(chat_id, "❌ Please enter a valid number.")
        return

    # Swap response
    active = r.hget("active_swap_requests", str(user_id))
    if active:
        text_l = text.lower()
        if text_l not in ["yes", "y", "no", "n"]:
            return
        swap_data = json.loads(active.decode() if isinstance(active, bytes) else active)
        if text_l in ["yes", "y"]:
            duty_schedule = json.loads(r.get("duty_schedule") or '{}')
            duty_schedule[swap_data["requester_slot"]] = swap_data["target"]
            duty_schedule[swap_data["target_slot"]] = swap_data["requester"]
            r.set("duty_schedule", json.dumps(duty_schedule))
            msg = f"✅ *Duty Swap Completed!*\n\n📅 {swap_data['requester_slot']}: {swap_data['target']}\n📅 {swap_data['target_slot']}: {swap_data['requester']}"
            send_message(chat_id, msg)
            send_message(swap_data["requester_chat_id"], msg)
            send_message(GROUP_CHAT_ID, msg)
        else:
            send_message(chat_id, "✅ You declined the swap request.")
            send_message(swap_data["requester_chat_id"], f"❌ {swap_data['target']} declined the swap request.")
        r.hdel("active_swap_requests", str(user_id))
        return
