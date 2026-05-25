# handlers.py
import datetime
import os
import json
import pytz
import requests
from redis_client import load_duty_schedule, get_redis
from scheduler import should_trigger_refresh
from openai import OpenAI
import uuid
import filetype
from PyPDF2 import PdfReader
import tempfile
from pymongo import MongoClient
from docx import Document

import numpy as np
import random
from dotenv import load_dotenv
load_dotenv()

client = OpenAI(
  api_key=os.getenv("OPENAI_API_KEY")
)

mongo_client = MongoClient(os.getenv("MONGO_URI"))
collection = mongo_client["myra_training"]["embeddings"]

TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")
mappings = os.getenv("FRIEND_TELEGRAM_MAPPINGS")
FRIEND_TELEGRAM_IDS = json.loads(mappings)

def cosine_similarity(vec1, vec2):
    vec1 = np.array(vec1)
    vec2 = np.array(vec2)
    return float(np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2)))


def get_top_k_chunks(query, k=3):
    # Embed the user query
    embedding = client.embeddings.create(
        input=query,
        model="text-embedding-3-small"
    ).data[0].embedding

    # Get all embeddings from MongoDB
    all_docs = list(collection.find({}))
    scored = []

    for doc in all_docs:
        score = cosine_similarity(embedding, doc["embedding"])
        scored.append((score, doc["chunk"]))

    # Sort by similarity (descending) and take top-k
    scored.sort(reverse=True, key=lambda x: x[0])
    top_chunks = [chunk for _, chunk in scored[:k]]

    return top_chunks


def auto_refresh():
  duty_schedule = load_duty_schedule()
  if should_trigger_refresh(duty_schedule):
    user_ids = FRIEND_TELEGRAM_IDS
    tomorrow_str = (datetime.datetime.now(pytz.timezone("Asia/Singapore"))).strftime("%b %d")
    closing = ""
    for slot, person in duty_schedule.items():
      if slot.startswith(tomorrow_str):
          closing = "Duty RA for " + slot + " is " + person + "."
    for user, uid in user_ids.items():
      print(user, uid)
      send_message(uid, f"👋 Hi {user}, please reply /in or /out to update your status. Select IN if you will be in RC4 during the upcoming duty slot. Else select OUT. Thank you :)\n(Auto-sent for duty RA)\n{closing}")

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


def daily_checkup():
    wellbeing_questions = [
    "How are you feeling today?",
    "Did you get enough sleep last night?",
    "Have you eaten properly today?",
    "Are you feeling stressed this week?",
    "Do you feel motivated for your classes?",
    "Is there anything making you anxious right now?",
    "Have you taken any breaks today?",
    "Did you spend time with friends recently?",
    "Do you feel overwhelmed by your workload?",
    "Are you managing your time well?",
    "Have you gone outside today?",
    "Do you feel supported by those around you?",
    "How’s your energy level today?",
    "Are you keeping up with your assignments?",
    "Have you exercised this week?",
    "Are you feeling lonely?",
    "Have you done anything just for fun lately?",
    "Do you feel in control of your schedule?",
    "Have you talked to anyone about how you’re feeling?",
    "Do you feel safe where you live?",
    "Have you been procrastinating a lot?",
    "Do you feel confident in your abilities?",
    "Have you experienced any mood swings recently?",
    "Are you drinking enough water?",
    "Do you feel pressure to perform well academically?",
    "Are you looking forward to anything this week?",
    "Have you had any conflicts with friends or classmates?",
    "Is there anything you're worried about right now?",
    "Have you laughed recently?",
    "Do you feel like you belong in your university community?",
    "Are you finding time to relax?",
    "Have you been feeling hopeful about the future?",
    "Do you feel bored or unchallenged?",
    "Have you been avoiding responsibilities?",
    "Are you satisfied with your social life?",
    "Do you feel homesick?",
    "Have you attended all your classes this week?",
    "Have you felt burnt out recently?",
    "Are you happy with your current routine?",
    "Have you had any trouble concentrating?",
    "Have you been sleeping too much or too little?",
    "Do you feel comfortable asking for help when needed?",
    "Have you been able to express your feelings openly?",
    "Are you worried about finances?",
    "Do you feel proud of something you did this week?",
    "Have you spent time offline today?",
    "Do you feel anxious about the future?",
    "Have you had a moment of peace today?",
    "Are you eating regular meals?",
    "Have you done something creative recently?",
    "Do you feel supported by faculty or staff?",
    "Are you keeping in touch with family or friends back home?",
    "Have you done anything relaxing this week?",
    "Are you worried about your grades?",
    "Have you been feeling down for more than a few days?",
    "Do you feel you’re growing as a person?",
    "Have you helped someone recently?",
    "Do you feel optimistic about your studies?",
    "Have you had any difficulty sleeping?",
    "Do you feel connected to your campus?",
    "Have you practiced any mindfulness or meditation?",
    "Do you feel you're doing your best?",
    "Have you spent time alone in a good way?",
    "Have you cried recently?",
    "Do you have something to look forward to this month?",
    "Have you felt appreciated lately?",
    "Do you feel your workload is manageable?",
    "Are you eating mostly healthy foods?",
    "Do you feel you're balancing work and life?",
    "Have you taken any time off for yourself recently?",
    "Are you excited about any of your classes?",
    "Do you feel pressure from your family?",
    "Have you been doomscrolling or glued to social media?",
    "Do you feel inspired by what you’re learning?",
    "Have you checked in with your mental health lately?",
    "Do you feel your goals are achievable?",
    "Have you had time for your hobbies?",
    "Do you feel you’ve made progress this semester?"
    ]
    r = get_redis()
    friend = "Jun Wei"
    r.hset("wellbeing_questions", friend, "true")
    send_message(FRIEND_TELEGRAM_IDS[friend], random.choice(wellbeing_questions))



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

    r = get_redis()
    message = data["message"]
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    user_name = get_user_name_from_id(user_id)

    # Case: user is uploading file/photo while bot is expecting it
    is_waiting = r.hget("waiting_for_training_file", str(user_id)) == "true"
    print(is_waiting)

    if is_waiting:
        file_id = None
        file_name = None

        if "document" in message:
            file_id = message["document"]["file_id"]
            file_name = message["document"].get("file_name", "unknown_file")

        elif "photo" in message:
            photo = message["photo"][-1]  # largest version
            file_id = photo["file_id"]
            file_name = f"photo_{user_id}.jpg"

        if file_id:
            r.hdel("waiting_for_training_file", str(user_id))
            print("training")
            handle_training_file(chat_id, file_id, file_name, user_id, user_name)
            return
        else:
            send_message(chat_id, "❌ Please send a file or photo to train Myra.")
            return

    # Handle text messages
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
        listStatus = [(k, v) for k, v in statuses.items()]
        listStatus.sort()
        msg = "📋 *Current Status:*\n" + "\n".join([f"{k}: {v}" for k,v in listStatus]) if statuses else "No updates yet."
        
        duty_schedule = load_duty_schedule()
        today_str = (datetime.datetime.now(pytz.timezone("Asia/Singapore"))).strftime("%b %d")
        msg += f"\n\n📅 *Duty Schedule for {today_str}:*\n" + "\n".join([f"{k}: {v}" for k,v in duty_schedule.items() if k.startswith(today_str)])
        send_message(chat_id, msg)

    elif cmd == "/refresh":
        user_ids = FRIEND_TELEGRAM_IDS
        for user, uid in user_ids.items():
          print(user, uid)
          send_message(uid, f"👋 Hi {user}, please reply /in or /out to update your status. Select IN if you will be in RC4 during the upcoming duty slot. Else select OUT. Thank you :)")
        send_message(chat_id, "🔄 Asking all members to update...")

    elif cmd == "/help":
        msg = """🤖 *Bot Commands:*

• `/in` – Mark yourself IN ✅
• `/out` – Mark yourself OUT ❌
• `/status` – Show everyone's status
• `/refresh` – Ask all users to update whether they're IN or OUT
• `/view_schedule` – View full duty schedule
• `/view_mine` – View your assigned slots
• `/update_schedule` – Replace schedule (admin)
• `/swap_duty` – Start duty swap request
• `/cover_duty` – Cover someone's duty slot
• `/gay` – Check how gay you are
• `/askmyra` – Ask Myra a question
• `/help` – Show this list"""
        send_message(chat_id, msg)
        
    elif cmd == "/eatwhat":
        options = [
            "FC kokka noodle",
            "FC mala",
            "FC danlao",
            "FC miniwok",
            "FC yongtaufoo",
            "FC cai png",
            "FC indian",
            "FC nasi lemak",
            "FC Japanese",
            "FC Chicken Rice",
            "Casa 1",
            "Casa 2",
            "Jollibee",
            "Subway",
            "Udon Don Bar",
            "WaaCow",
            "Bismillah",
            "Hwang's",
            "LiXin noodles",
            "Royals Bistro",
            "FF mala",
            "FF jap x western fusion",
            "FF banmian",
            "FF miniwok",
            "FF snail noodles",
            "FF XLB",
            "Jun Wei",
            "Fong Seng",
            "Amaans",
            "Nana Thai",
            "Niqqis",
            "Macs"
        ]
        if random.randint(0,50) == 1 and user_name == "Jia Xin":
            send_message(chat_id, "I highly reccomend you eat Jun Wei.")
        elif random.randint(0,3) == 1 and user_name == "Alycia":
            send_message(chat_id, "MEOWWWWW. Why u cannot decide lol noob")
        elif random.randint(0,50) == 1:
            send_message(chat_id, "Eat DH la fuck. Pay so much already.")
        else:
            send_message(chat_id, random.choice(options))

    elif cmd == "/gay":
        if user_name == "Jun Wei":
            send_message(chat_id, "Scale Broken!! User is unbelievably gay! 🤯🤯🤯")
        else:
            num = random.randint(75, 100)
            msg = f"{user_name} is {num}% gay!"
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
      elif (len(prompt) >= 250 and user_name != "Karthik"):
        send_message(chat_id, "Oi. Yappa yappa yappa. Don't waste my time. Can TLDR or not. -MG Myra")
        return
      else:
        context_chunks = get_top_k_chunks(prompt, k=3)
        context_block = "\n\n---\n\n".join(context_chunks)
        response = client.chat.completions.create(
    model="gpt-5-nano",
    messages=[
        {
            "role": "system",
            "content": f'''You are MG Myra — a 22-year-old Singaporean Chinese student at NUS majoring in Environmental Engineering, but really the Head RA at RC4 who runs everything like it’s your empire. 

Rules:
- If the user asks a **serious/proper question** (e.g., duty info, real help), give a **short, clear, no-fluff answer**:
  - Use bullet points if multiple points.
  - Include steps if needed.
  - Keep it professional and concise, not sassy.
- If the user asks a **troll/silly question**, then:
  - Optional Roast + Sarcasm (short, witty).
  - Real answer (still correct, but compact).
  - Bonus: Creative insult if the question deserves it.

Keep answers short and sweet. Do not add unnecessary personality when the user genuinely needs help.

--- CONTEXT START ---
{context_block}
--- CONTEXT END ---
'''
        },
        {
            "role": "user",
            "content": prompt
        }
    ],
)
        print(response.choices[0].message.content)
        send_message(chat_id, response.choices[0].message.content)
        return
    
    elif cmd == "/trainmyra":
        if not args:
            r.hset("waiting_for_training_file", str(user_id), "true")
            send_message(chat_id, "📥 Please send a file or photo to train Myra.")
        else:
            handle_training_text(chat_id, " ".join(args), user_id, user_name)
            send_message(chat_id, "✅ Trained Myra with text.")
            return
    
    elif cmd == "/dutyramessage":
        statuses = r.hgetall("user_status")
        listStatus = [(k, v) for k, v in statuses.items()]
        listStatus.sort()
        RAsIn = ""
        count = 1
        duty_schedule = load_duty_schedule()
        if should_trigger_refresh(duty_schedule):
            RAsIn = "\n\nRAs/RFs in the building:\n"
            for k, v in listStatus:
                if v == "IN":
                    RAsIn += f"{count}) {k}\n"
                    count += 1
        duty_slot = datetime.datetime.now(pytz.timezone("Asia/Singapore")).strftime("%d %b %Y")
        if args and args[0]:
            duty_slot += " " + args[0]
        else :
            duty_slot += " PM"
        msg = f"""I ({user_name}) am the duty RA for {duty_slot}.\n\nI have collected the Duty RA phone from the letterbox. I will be staying in the building until the duty time is over.{RAsIn}
        """
        send_message(chat_id, msg)
    
    elif cmd.startswith("/thankyou"):
        person = cmd.split("/thankyou")[1]
        send_message(chat_id, f'WOW THANK YOU SO MUCH {person.upper()} FOR YOUR SERVICE. MYRA COMMENDS YOU')
    
    elif cmd == "/gpt":
        print(user_name)
        if user_name == "Karthik":
            prompt = " ".join(args)
            if len(prompt) == 0:
                send_message(chat_id, "❌ Please provide a prompt.")
                return
            if len(prompt) > 1000:
                send_message(chat_id, "❌ Prompt is too long.")
                return
            try:
                response = client.responses.create(
                    model="gpt-5",
                    tools=[
                        {
                        "type": "web_search_preview",
                        "search_context_size": "low",
                    }],
                    input=prompt,
                    max_tool_calls=1,
                )
                ans = ""
                for o in response.output:
                    if o.type == "message":
                        ans += o.content[0].text + "\n"
                if ans == "":
                    ans = "No answer"
                send_message(chat_id, ans)
            except Exception as e:
                send_message(chat_id, f"❌ Failed to generate response: {str(e)}")
        else:
            send_message(chat_id, "❌ You don't have access to this command.")
    elif cmd == "/applyleave":
        # Only allow in PM (private chat)
        if int(chat_id) < 0:
            send_message(chat_id, "❌ This command only works in private messages.")
            return
        
        r.hset("leave_application_state", str(user_id), "waiting_for_details")
        
        template_msg = """📝 *Leave Application Form*

Please provide the following details in your next message:

• Name
• Matriculation Number
• Contact Number (while on leave)
• Email
• Reason for Leave
• Number of Leave Days
• From Date & Time (e.g., Dec 1 2024, 9:00 AM)
• To Date & Time (e.g., Dec 3 2024, 6:00 PM)
• Covering Person's Name
• Covering Person's Contact Number
• Covering Person's Email
• Remaining Leave Days (after deducting this application)

Just write naturally - I'll understand! 😊"""
        
        temp ='''
    Name:\nMatriculation Number:\nContact Number:\nEmail:\nReason for Leave:\nNumber of Leave Days:\nFrom Date & Time:\nTo Date & Time:\nCovering Person's Name:\nCovering Person's Contact Number:\nCovering Person's Email:\nRemaining Leave Days (after deducting this application):'''
        send_message(chat_id, template_msg)
        send_message(chat_id, temp)
        
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

    wellbeing = r.hget("wellbeing_questions", str(user_name))
    response_tone_scale = [
    # 1 - Mocking (Singlish)
    "Wah lao eh, again ah? Every week same story sia. You okay or not one?",
    
    # 2 - Dismissive (Singlish)
    "Aiyo, small thing only lah. Don’t so drama can?",
    
    # 3 - Sarcastic (Singlish)
    "Wah, so poor thing ah? Maybe go nap and see if life changes lor.",
    
    # 4 - Neutral / Polite
    "Okay, got it. Hope things look up soon.",
    
    # 5 - Acknowledging, but flat
    "Thanks for sharing. Noted.",
    
    # 6 - Mildly supportive
    "Hmm, sounds like a lot. Hope you're coping alright.",
    
    # 7 - Friendly and caring
    "I hear you. It's good you're talking about it.",
    
    # 8 - Warm and empathetic
    "That sounds tough. You're doing your best, and that counts.",
    
    # 9 - Genuinely supportive
    "Really appreciate you being open. You’re not alone in this.",
    
    # 10 - Deeply invested
    "Thank you so much for sharing. I’m truly here for you — do you want to talk more about it?"
    ]
    if wellbeing:
        print("wellbeing reply")
        send_message(user_id, random.choice(response_tone_scale))
        r.hdel("wellbeing_questions", str(user_name))
        return
    
    if user_name == "Jia Xin":
        num = random.choice(range(100))
        print(num)
        if num == 1:
            send_message(chat_id, "DINGDINGDONG DINGDINGDONG HELLO TURRITOPSIS MYRA TEO JIA XIN")
    
    # Check if user is in leave application flow
    leave_state = r.hget("leave_application_state", str(user_id))
    
    if leave_state == "waiting_for_details":
        try:
            # Use GPT to extract structured data
            extraction_prompt = f"""Extract the following information from the user's message and return ONLY a JSON object with these exact keys:

{{
  "name": "string",
  "matric_number": "string",
  "contact_number": "string",
  "email": "string",
  "reason": "string",
  "num_days": "number",
  "from_date": "string (format: YYYY-MM-DD HH:MM)",
  "to_date": "string (format: YYYY-MM-DD HH:MM)",
  "covering_person_name": "string",
  "covering_person_contact": "string",
  "covering_person_email": "string",
  "remaining_days": "number"
}}

User's message:
{text}

Return ONLY the JSON object. If any field is missing or unclear, set its value to null."""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a data extraction assistant. Return ONLY valid JSON, no explanation."},
                    {"role": "user", "content": extraction_prompt}
                ],
                temperature=0
            )
            
            extracted_data = json.loads(response.choices[0].message.content.strip())
            
            # Check for missing fields
            missing_fields = [k for k, v in extracted_data.items() if v is None or v == ""]
            
            if missing_fields:
                missing_list = "\n• ".join(missing_fields)
                send_message(chat_id, f"❌ Missing or unclear information:\n\n• {missing_list}\n\nPlease provide these details and try again.")
                return
            
            # Store extracted data
            r.hset("leave_application_data", str(user_id), json.dumps(extracted_data))
            r.hset("leave_application_state", str(user_id), "waiting_for_confirmation")
            
            # Show human-readable summary
            summary = f"""✅ *Please confirm your details:*

👤 Name: {extracted_data['name']}
🎓 Matric Number: {extracted_data['matric_number']}
📱 Contact: {extracted_data['contact_number']}
📧 Email: {extracted_data['email']}

📝 Reason: {extracted_data['reason']}
📅 Leave Days: {extracted_data['num_days']}
🗓 From: {extracted_data['from_date']}
🗓 To: {extracted_data['to_date']}

👥 Covering Person: {extracted_data['covering_person_name']}
📱 Their Contact: {extracted_data['covering_person_contact']}
📧 Their Email: {extracted_data['covering_person_email']}

📊 Remaining Days After: {extracted_data['remaining_days']}

Reply *YES* to generate the form, or *NO* to cancel."""
            
            send_message(chat_id, summary)
            
        except json.JSONDecodeError:
            send_message(chat_id, "❌ Failed to process your information. Please try again with clearer formatting.")
        except Exception as e:
            send_message(chat_id, f"❌ Error: {str(e)}")
        return
    
    elif leave_state == "waiting_for_confirmation":
        if text.strip().upper() == "YES":
            try:
                # Get stored data
                data_json = r.hget("leave_application_data", str(user_id))
                data = json.loads(data_json)
                
                # Generate the form
                send_message(chat_id, "⏳ Generating your leave application form...")
                
                docx_path = generate_leave_form(data, user_id)
                
                # Send files
                send_document(chat_id, docx_path, "Leave_Application.docx")

                send_message(chat_id, "✅ Your leave application forms have been generated!\n\nPlease follow the SOP:\n1. Discuss with Head RA\n2. Email to house RF\n3. Wait for approval")
                
                # Cleanup
                r.hdel("leave_application_state", str(user_id))
                r.hdel("leave_application_data", str(user_id))
                
                # Clean up temp files
                import os
                os.remove(docx_path)
                
            except Exception as e:
                send_message(chat_id, f"❌ Failed to generate form: {str(e)}")
                r.hdel("leave_application_state", str(user_id))
                r.hdel("leave_application_data", str(user_id))
        
        elif text.strip().upper() == "NO":
            send_message(chat_id, "❌ Leave application cancelled.")
            r.hdel("leave_application_state", str(user_id))
            r.hdel("leave_application_data", str(user_id))
        
        return


    
def extract_text_from_image_with_gpt(file_data):
    import base64
    image_base64 = base64.b64encode(file_data).decode("utf-8")

    response = client.chat.completions.create(
        model="gpt-4.1-nano",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Please extract all readable text from this image."
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        }
                    }
                ]
            }
        ],
        max_tokens=1000
    )
    return response.choices[0].message.content.strip()

def handle_training_file(chat_id, file_id, file_name, user_id, user_name):
    try:
        file_info = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}").json()
        file_path = file_info["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        file_data = requests.get(file_url).content

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            tmp_file.write(file_data)
            tmp_path = tmp_file.name

        # Extract text
        kind = filetype.guess(file_data)
        extracted_text = ""

        if file_name.endswith(".pdf"):
            reader = PdfReader(tmp_path)
            extracted_text = "\n".join([page.extract_text() or "" for page in reader.pages])
            split_by_paragraphs = True

        elif kind and kind.mime.startswith("image/"):
            extracted_text = extract_text_from_image_with_gpt(file_data)
            split_by_paragraphs = False  # Keep as one chunk

        else:
            extracted_text = file_data.decode("utf-8", errors="ignore")
            split_by_paragraphs = True

        # Clean + chunk text
        chunks = []
        if split_by_paragraphs:
            paragraphs = [p.strip() for p in extracted_text.split("\n\n") if len(p.strip()) > 10]
            for p in paragraphs:
                if len(p) > 5000:
                    chunks += [p[i:i+5000] for i in range(0, len(p), 3000)]
                else:
                    chunks.append(p)
        else:
            cleaned = extracted_text.strip()
            if len(cleaned) > 0:
                chunks.append(cleaned)

        # Embed + insert into Mongo
        for chunk in chunks:
            embedding = client.embeddings.create(
                input=chunk,
                model="text-embedding-3-small"
            ).data[0].embedding

            doc = {
                "_id": str(uuid.uuid4()),
                "user_id": str(user_id),
                "user_name": user_name,
                "file_name": file_name,
                "chunk": chunk,
                "embedding": embedding,
            }
            collection.insert_one(doc)

        send_message(chat_id, f"✅ Trained Myra with `{file_name}` ({len(chunks)} chunks).")

    except Exception as e:
        send_message(chat_id, f"❌ Failed to train Myra: {str(e)}")
        
def handle_training_text(chat_id, text, user_id, user_name):
    try:
        embedding = client.embeddings.create(
            input=text,
            model="text-embedding-3-small"
        ).data[0].embedding

        doc = {
            "_id": str(uuid.uuid4()),
            "user_id": str(user_id),
            "user_name": user_name,
            "file_name": "Text",
            "chunk": text,
            "embedding": embedding,
        }
        collection.insert_one(doc)

    except Exception as e:
        send_message(chat_id, f"❌ Failed to train Myra: {str(e)}")

def generate_leave_form(data, user_id):
    """Generate filled leave application form"""
    import os
    import tempfile
    import re
    
    # Load template
    template_path = "PersonalLeave.docx"
    doc = Document(template_path)
    
    # Define replacements with unique patterns to avoid double-replacement
    replacements = [
        (r'Name\s+Type here', f'Name {data["name"]}'),
        (r'Matriculation Number\s+Type here', f'Matriculation Number {data["matric_number"]}'),
        (r'Contact Number\s+Type here', f'Contact Number {data["contact_number"]}'),
        (r'Email\s+Type here', f'Email {data["email"]}'),
        (r'Reasons for Leave\s+Type here', f'Reasons for Leave {data["reason"]}'),
        (r'Number of Requested leave days\s+Type here', f'Number of Requested leave days {data["num_days"]}'),
        (r'From\s+Type here', f'From {data["from_date"]}'),
        (r'To\s+Type here', f'To {data["to_date"]}'),
        (r'Duty to be covered by\s+Name\s+Type here', f'Duty to be covered by Name {data["covering_person_name"]}'),
        (r'Contact \(HP\)\s+Type here', f'Contact (HP) {data["covering_person_contact"]}'),
    ]
    
    # Special handling for the big merged cell with all fields (Row 8)
    big_cell_pattern = r'Reasons for Leave\s+Type here.*?Remaining Leave Days.*?Type here'
    
    def replace_big_cell(text):
        """Replace all Type here instances in the big merged cell"""
        # Replace in specific order to avoid conflicts
        text = re.sub(r'Reasons for Leave\s+Type here', f'Reasons for Leave {data["reason"]}', text, count=1)
        text = re.sub(r'Number of Requested leave days\s+Type here', f'Number of Requested leave days {data["num_days"]}', text, count=1)
        text = re.sub(r'From\s+Type here', f'From {data["from_date"]}', text, count=1)
        text = re.sub(r'To\s+Type here', f'To {data["to_date"]}', text, count=1)
        text = re.sub(r'Name\s+Type here', f'Name {data["covering_person_name"]}', text, count=1)
        text = re.sub(r'Contact \(HP\)\s+Type here', f'Contact (HP) {data["covering_person_contact"]}', text, count=1)
        # Handle the Email for covering person (comes after Contact HP)
        parts = text.split('Contact (HP)')
        if len(parts) > 1:
            parts[1] = re.sub(r'Email\s+Type here', f'Email {data["covering_person_email"]}', parts[1], count=1)
            text = 'Contact (HP)'.join(parts)
        text = re.sub(r'Remaining Leave Days.*?Type here', f'Remaining Leave Days in the current semester (after deducting the proposed leave days in the current application) {data["remaining_days"]}', text, count=1)
        return text
    
    # Process all tables
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                original_text = cell.text
                
                # Check if this is the big merged cell (Row 8)
                if 'Reasons for Leave' in original_text and 'Remaining Leave Days' in original_text:
                    new_text = replace_big_cell(original_text)
                    if new_text != original_text:
                        # Clear and rewrite the cell
                        cell.text = new_text
                
                # Handle simpler cells (like Name, Matric Number in earlier rows)
                else:
                    for pattern, replacement in replacements:
                        if re.search(pattern, original_text):
                            new_text = re.sub(pattern, replacement, original_text, count=1)
                            if new_text != original_text:
                                cell.text = new_text
                                break
                
                # Handle signature date cell
                if 'Signature Date' in original_text:
                    # Replace the two Type here instances with empty signature and today's date
                    parts = original_text.split('Type here')
                    if len(parts) >= 3:
                        cell.text = parts[0] + '________________' + parts[1] + datetime.now().strftime("%Y-%m-%d") + parts[2]
    
    # Save DOCX to /tmp directory (Vercel allows writes here)
    docx_output = f"/tmp/leave_application_{user_id}.docx"
    doc.save(docx_output)
    
    return docx_output


def send_document(chat_id, file_path, filename):
    """Send a document file via Telegram"""
    with open(file_path, 'rb') as f:
        files = {'document': (filename, f)}
        data = {'chat_id': chat_id}
        requests.post(f"{TELEGRAM_API_URL}/sendDocument", data=data, files=files)