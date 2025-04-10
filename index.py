import os
import json
import logging
from datetime import datetime, timedelta, time
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
import traceback

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    filename='bot_log.log'
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Get bot token from environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN found in environment variables! Create a .env file with BOT_TOKEN=your_token")

# Load syllabi from JSON file 📂
def load_syllabi():
    try:
        with open('syllabi.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"current_field": "", "syllabi": {}}

def save_syllabi(data):
    with open('syllabi.json', 'w') as f:
        json.dump(data, f, indent=4)

# Progress tracking 📊
def load_progress():
    try:
        with open('progress.json', 'r') as f:
            data = json.load(f)
            # Initialize global settings if not present
            if "global_settings" not in data:
                data["global_settings"] = {
                    "reminder_interval": 7,  # Default 7 days per task
                    "reminders_enabled": True,  # Notifications enabled by default
                    "last_check": datetime.now().isoformat()
                }
            return data
    except FileNotFoundError:
        return {
            "global_settings": {
                "reminder_interval": 7,  # Default 7 days per task
                "reminders_enabled": True,  # Notifications enabled by default
                "last_check": datetime.now().isoformat()
            },
            "syllabi_progress": {}  # Will store progress for each syllabus separately
        }

def save_progress(data):
    with open('progress.json', 'w') as f:
        json.dump(data, f, indent=4)

# Update or get progress for a specific syllabus
def get_syllabus_progress(progress, syllabus_name):
    """Get progress for a specific syllabus, initializing if needed"""
    if "syllabi_progress" not in progress:
        progress["syllabi_progress"] = {}
        
    if syllabus_name not in progress["syllabi_progress"]:
        progress["syllabi_progress"][syllabus_name] = {
            "current_week": 1,
            "completed_weeks": [],
            "start_date": datetime.now().isoformat(),
            "due_date": (datetime.now() + timedelta(days=progress["global_settings"].get("reminder_interval", 7))).isoformat()
        }
    
    return progress["syllabi_progress"][syllabus_name]

# Function to update due date when starting a new task
def update_due_date(progress, syllabus_name):
    """Update the due date for the current task"""
    syllabus_progress = get_syllabus_progress(progress, syllabus_name)
    interval = progress["global_settings"].get("reminder_interval", 7)
    syllabus_progress["due_date"] = (datetime.now() + timedelta(days=interval)).isoformat()
    return progress

# Error handler decorator for commands
def handle_errors(func):
    async def wrapper(update, context, *args, **kwargs):
        try:
            return await func(update, context, *args, **kwargs)
        except FileNotFoundError as e:
            logger.error(f"File not found error: {str(e)}")
            await update.message.reply_text(
                "⚠️ Data file not found. This might be your first time using the bot. "
                "Try using /start to initialize your progress tracking!"
            )
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {str(e)}")
            await update.message.reply_text(
                "⚠️ There was an error reading the data file. "
                "The format might be corrupted. Contact the administrator for help."
            )
        except IndexError as e:
            logger.error(f"Index error: {str(e)}")
            await update.message.reply_text(
                "⚠️ Task index out of range. Make sure you have selected a syllabus with /start."
            )
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}\n{traceback.format_exc()}")
            await update.message.reply_text(
                "⚠️ An unexpected error occurred. Please try again later or contact the administrator."
            )
    return wrapper

# Bot handlers 🎮
@handle_errors
async def start(update: Update, context):
    """Handler for the /start command with syllabus selection. 🌟"""
    syllabi = load_syllabi()
    if not syllabi["syllabi"]:
        await update.message.reply_text("No syllabi available. Please add some manually to syllabi.json. 🚧")
        return
    keyboard = [
        [InlineKeyboardButton(f"{field} {'(Paused ⏸️)' if syllabi['syllabi'][field].get('paused', False) else '(Active ▶️)'}", callback_data=f"start_{field}")]
        for field in syllabi["syllabi"]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a syllabus to start or resume: 📚🎉", reply_markup=reply_markup)

@handle_errors
async def start_syllabus_callback(update: Update, context):
    """Handle syllabus selection from /start. 🔄"""
    query = update.callback_query
    await query.answer()
    field_name = query.data.replace("start_", "")
    syllabi = load_syllabi()
    progress = load_progress()
    
    if field_name in syllabi["syllabi"] and not syllabi["syllabi"][field_name].get("paused", False):
        syllabi["current_field"] = field_name
        save_syllabi(syllabi)
        
        # Get or initialize progress for this syllabus
        syllabus_progress = get_syllabus_progress(progress, field_name)
        current_week = syllabus_progress["current_week"]
        
        # Update due date for new task if starting fresh
        if current_week == 1 and not syllabus_progress["completed_weeks"]:
            update_due_date(progress, field_name)
            save_progress(progress)
        
        task_index = current_week - 1
        if task_index >= len(syllabi["syllabi"][field_name]["tasks"]):
            # Reset if we're beyond the end (shouldn't happen normally)
            task_index = 0
            syllabus_progress["current_week"] = 1
            save_progress(progress)
            
        days_remaining = "Unknown"
        if "due_date" in syllabus_progress:
            due_date = datetime.fromisoformat(syllabus_progress["due_date"])
            days_remaining = (due_date - datetime.now()).days
            
        status_text = "Starting with" if current_week == 1 and not syllabus_progress["completed_weeks"] else "Continuing with"
        
        await query.edit_message_text(
            f"Switched to '{field_name}' syllabus! 🌱\n\n"
            f"{status_text}:\n\n"
            f"{syllabi['syllabi'][field_name]['tasks'][task_index]}\n\n"
            f"Due in {days_remaining} days. Use /check when completed! 🚀"
        )
    else:
        await query.edit_message_text(f"'{field_name}' is paused. Resume with /resume_syllabus. 🚧")

@handle_errors
async def help_command(update: Update, context):
    """Handler for the /help command. ℹ️"""
    await update.message.reply_text(
        "Here are the available commands: 📋\n\n"
        "Basic Commands:\n"
        "- /start - Select a syllabus to begin or resume 🌱\n"
        "- /help - Show this help message ℹ️\n"
        "- /current - Show your current task ⏰\n"
        "- /check - Check off your current task as completed ✅\n\n"
        
        "Syllabus Management:\n"
        "- /show_all_syllabi - List all available syllabi 📚\n"
        "- /switch_syllabus - Switch to another syllabus 🔄\n"
        "- /pause_syllabus - Pause tracking for a syllabus ⏸️\n"
        "- /resume_syllabus - Resume tracking for a syllabus ▶️\n\n"
        
        "Progress & Timing:\n"
        "- /completed - Show all completed tasks ✅\n"
        "- /statistics - View your progress statistics 📊\n"
        "- /set_interval <days> - Change how many days per task ⏱️\n"
        "- /reset - Start over from the beginning 🔄\n\n"
        
        "Reminder Settings:\n"
        "- /toggle_reminders - Turn reminders on/off 🔔\n\n"
        
        "Note: Edit syllabi manually in syllabi.json. 📝"
    )

@handle_errors
async def current_week(update: Update, context):
    """Show the current week's task. ⏳"""
    syllabi = load_syllabi()
    progress = load_progress()
    if not syllabi["current_field"] or syllabi["syllabi"][syllabi["current_field"]].get("paused", False):
        await update.message.reply_text("No active syllabus or it's paused. Use /start or /resume_syllabus. 🚧")
        return
    
    current_field = syllabi["current_field"]
    syllabus_progress = get_syllabus_progress(progress, current_field)
    current_week = syllabus_progress["current_week"]
    
    try:
        if 0 < current_week <= len(syllabi['syllabi'][current_field]["tasks"]):
            # Calculate days remaining
            days_remaining = "Unknown"
            status = ""
            
            if "due_date" in syllabus_progress:
                due_date = datetime.fromisoformat(syllabus_progress["due_date"])
                days = (due_date - datetime.now()).days
                
                if days < 0:
                    days_remaining = abs(days)
                    status = f"(OVERDUE by {days_remaining} days! ⚠️)"
                else:
                    days_remaining = days
                    status = f"(Due in {days_remaining} days ⏱️)"
            
            await update.message.reply_text(
                f"Current task ({current_field}): 🌟\n\n"
                f"{syllabi['syllabi'][current_field]['tasks'][current_week-1]}\n\n"
                f"{status}"
            )
        else:
            await update.message.reply_text("No current task. Use /start to begin. 🌱")
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}. Please try again or use /start. 🚧")

@handle_errors
async def show_completed(update: Update, context):
    """Show completed weeks. ✅"""
    syllabi = load_syllabi()
    progress = load_progress()
    if not syllabi["current_field"] or syllabi["syllabi"][syllabi["current_field"]].get("paused", False):
        await update.message.reply_text("No active syllabus or it's paused. Use /start or /resume_syllabus. 🚧")
        return
    
    current_field = syllabi["current_field"]
    syllabus_progress = get_syllabus_progress(progress, current_field)
    
    try:
        completed = []
        for i in syllabus_progress["completed_weeks"]:
            if i < len(syllabi['syllabi'][current_field]['tasks']):
                task = syllabi['syllabi'][current_field]['tasks'][i]
                
                # Add completion date if available
                date_info = ""
                if "completion_dates" in syllabus_progress and str(i) in syllabus_progress["completion_dates"]:
                    completion_date = datetime.fromisoformat(syllabus_progress["completion_dates"][str(i)])
                    date_info = f" (completed on {completion_date.strftime('%Y-%m-%d')})"
                
                completed.append(f"✅ {task}{date_info}")
        
        if completed:
            await update.message.reply_text(
                f"Completed tasks ({current_field}): 🎉\n\n"
                f"{chr(10).join(completed)}\n"
            )
        else:
            await update.message.reply_text("No tasks completed yet. 🚧 Keep going!")
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}. Please try again or use /start. 🚧")

@handle_errors
async def check_progress(update: Update, context):
    """Manually check if the current week's tasks are done. 🔍"""
    syllabi = load_syllabi()
    progress = load_progress()
    
    if not syllabi["current_field"] or syllabi["syllabi"][syllabi["current_field"]].get("paused", False):
        await update.message.reply_text("No active syllabus or it's paused. Use /start or /resume_syllabus. 🚧")
        return
        
    try:
        current_field = syllabi["current_field"]
        syllabus_progress = get_syllabus_progress(progress, current_field)
        current_week = syllabus_progress["current_week"]
        
        if current_week > 0 and current_week <= len(syllabi['syllabi'][current_field]["tasks"]):
            # Create proper InlineKeyboardMarkup with buttons
            keyboard = [
                [
                    InlineKeyboardButton("Yes ✅", callback_data="yes"),
                    InlineKeyboardButton("No 🚫", callback_data="no")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Show due date if available
            due_info = ""
            if "due_date" in syllabus_progress:
                due_date = datetime.fromisoformat(syllabus_progress["due_date"])
                days = (due_date - datetime.now()).days
                
                if days < 0:
                    due_info = f"\n\n⚠️ This task is overdue by {abs(days)} days!"
                else:
                    due_info = f"\n\nThis task is due in {days} days."
            
            await update.message.reply_text(
                f"Have you completed this task from {current_field}:\n\n"
                f"{syllabi['syllabi'][current_field]['tasks'][current_week-1]}{due_info}\n\n"
                f"Click a button: ⬇️",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text("No current task to check. Use /start to begin. 🌱")
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}. Please try again or use /start. 🚧")

@handle_errors
async def reset_progress(update: Update, context):
    """Reset progress to start from the beginning. 🔄"""
    syllabi = load_syllabi()
    if not syllabi["current_field"] or syllabi["syllabi"][syllabi["current_field"]].get("paused", False):
        await update.message.reply_text("No active syllabus or it's paused. Use /start or /resume_syllabus. 🚧")
        return
    
    # Create proper InlineKeyboardMarkup with buttons
    keyboard = [
        [
            InlineKeyboardButton("Yes, reset ✅", callback_data="reset_yes"),
            InlineKeyboardButton("No, cancel 🚫", callback_data="reset_no")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Are you sure you want to reset? 🔄 This will erase all progress for the current syllabus!\n\n"
        "Click a button: ⬇️",
        reply_markup=reply_markup
    )

@handle_errors
async def show_all_syllabi(update: Update, context):
    """Show all available syllabi. 🔍"""
    syllabi = load_syllabi()
    if syllabi["syllabi"]:
        keyboard = [
            [InlineKeyboardButton(f"{field} {'(Paused ⏸️)' if syllabi['syllabi'][field].get('paused', False) else '(Active ▶️)'}", callback_data=f"show_{field}")]
            for field in syllabi["syllabi"]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Select a syllabus to view details: 📚", reply_markup=reply_markup)
    else:
        await update.message.reply_text("No syllabi available. Please add some manually to syllabi.json. 🚧")

@handle_errors
async def show_syllabus_callback(update: Update, context):
    """Handle syllabus selection from /show_all_syllabi. 🔍"""
    query = update.callback_query
    await query.answer()
    field_name = query.data.replace("show_", "")
    syllabi = load_syllabi()
    progress = load_progress()
    
    if field_name in syllabi["syllabi"]:
        try:
            tasks = "\n".join([f"{i+1}. {task}" for i, task in enumerate(syllabi['syllabi'][field_name]["tasks"])])
            status = "(Paused ⏸️)" if syllabi["syllabi"][field_name].get("paused", False) else "(Active ▶️)"
            
            # Get progress info if available
            progress_info = ""
            if "syllabi_progress" in progress and field_name in progress["syllabi_progress"]:
                syllabus_progress = progress["syllabi_progress"][field_name]
                completed = len(syllabus_progress["completed_weeks"])
                total = len(syllabi['syllabi'][field_name]["tasks"])
                current = syllabus_progress["current_week"]
                
                # Prevent showing current week beyond total tasks
                if current > total:
                    current = "Completed"
                
                progress_info = f"\nCompleted: {completed}/{total} tasks\nCurrent week: {current}"
            
            await query.edit_message_text(
                f"Syllabus: {field_name} {status}\n"
                f"Total weeks: {len(syllabi['syllabi'][field_name]['tasks'])}{progress_info}\n\n"
                f"Tasks:\n{tasks}\n\n"
                f"Use /start to select or /switch_syllabus to switch! 🚀"
            )
        except Exception as e:
            await query.edit_message_text(f"Error displaying syllabus: {str(e)}. Please try again. 🚧")

@handle_errors
async def switch_syllabus(update: Update, context):
    """Switch to another syllabus with interactive selection. 🔄"""
    syllabi = load_syllabi()
    if not syllabi["syllabi"]:
        await update.message.reply_text("No syllabi to switch. Please add some manually to syllabi.json. 🚧")
        return
    keyboard = [
        [InlineKeyboardButton(f"{field} {'(Paused ⏸️)' if syllabi['syllabi'][field].get('paused', False) else '(Active ▶️)'}", callback_data=f"switch_{field}")]
        for field in syllabi["syllabi"]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a syllabus to switch to: 🔄", reply_markup=reply_markup)

@handle_errors
async def switch_syllabus_callback(update: Update, context):
    """Handle syllabus switch while preserving progress. 🔄"""
    query = update.callback_query
    await query.answer()
    
    field_name = query.data.replace("switch_", "")
    syllabi = load_syllabi()
    progress = load_progress()
    
    if field_name in syllabi["syllabi"] and not syllabi["syllabi"][field_name].get("paused", False):
        # Save current field to syllabi.json
        syllabi["current_field"] = field_name
        save_syllabi(syllabi)
        
        # Get or initialize progress for this syllabus
        syllabus_progress = get_syllabus_progress(progress, field_name)
        current_week = syllabus_progress["current_week"]
        
        # Update due date for this syllabus
        update_due_date(progress, field_name)
        save_progress(progress)
        
        # Determine if this is a new syllabus or one we're continuing
        status_text = "Starting with" if current_week == 1 and not syllabus_progress["completed_weeks"] else "Continuing with"
        task_index = current_week - 1
        
        # Make sure the task index is valid
        if task_index >= len(syllabi["syllabi"][field_name]["tasks"]):
            task_index = 0
            syllabus_progress["current_week"] = 1
            save_progress(progress)
        
        # Send confirmation message
        await query.edit_message_text(
            f"Switched to '{field_name}' syllabus! 🌱\n\n"
            f"{status_text}:\n\n"
            f"{syllabi['syllabi'][field_name]['tasks'][task_index]}\n\n"
            f"Due in {progress['global_settings'].get('reminder_interval', 7)} days. Use /check when completed. 🚀"
        )
    else:
        await query.edit_message_text(f"'{field_name}' is paused. Resume with /resume_syllabus. 🚧")

@handle_errors
async def pause_syllabus(update: Update, context):
    """Pause tracking for a syllabus. ⏸️"""
    syllabi = load_syllabi()
    if not syllabi["syllabi"]:
        await update.message.reply_text("No syllabi to pause. Please add some manually to syllabi.json. 🚧")
        return
    keyboard = [
        [InlineKeyboardButton(f"{field} {'(Paused ⏸️)' if syllabi['syllabi'][field].get('paused', False) else '(Active ▶️)'}", callback_data=f"pause_{field}")]
        for field in syllabi["syllabi"]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a syllabus to pause: ⏸️", reply_markup=reply_markup)

@handle_errors
async def pause_syllabus_callback(update: Update, context):
    """Handle pausing a syllabus. ⏸️"""
    query = update.callback_query
    await query.answer()
    field_name = query.data.replace("pause_", "")
    syllabi = load_syllabi()
    if field_name in syllabi["syllabi"]:
        try:
            syllabi["syllabi"][field_name]["paused"] = True
            if syllabi["current_field"] == field_name:
                syllabi["current_field"] = ""
            save_syllabi(syllabi)
            await query.edit_message_text(f"Tracking for '{field_name}' paused! ⏸️🎉 Use /resume_syllabus to continue.")
        except Exception as e:
            await query.edit_message_text(f"Error pausing syllabus: {str(e)}. Please try again. 🚧")
    else:
        await query.edit_message_text("Syllabus not found. 🚧")

@handle_errors
async def resume_syllabus(update: Update, context):
    """Resume tracking for a syllabus. ▶️"""
    syllabi = load_syllabi()
    if not syllabi["syllabi"]:
        await update.message.reply_text("No syllabi to resume. Please add some manually to syllabi.json. 🚧")
        return
    keyboard = [
        [InlineKeyboardButton(f"{field} {'(Paused ⏸️)' if syllabi['syllabi'][field].get('paused', False) else '(Active ▶️)'}", callback_data=f"resume_{field}")]
        for field in syllabi["syllabi"]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a syllabus to resume: ▶️", reply_markup=reply_markup)

@handle_errors
async def resume_syllabus_callback(update: Update, context):
    """Handle resuming a syllabus. ▶️"""
    query = update.callback_query
    await query.answer()
    field_name = query.data.replace("resume_", "")
    syllabi = load_syllabi()
    if field_name in syllabi["syllabi"]:
        try:
            syllabi["syllabi"][field_name]["paused"] = False
            save_syllabi(syllabi)
            await query.edit_message_text(f"Tracking for '{field_name}' resumed! ▶️🎉 Use /start to select it.")
        except Exception as e:
            await query.edit_message_text(f"Error resuming syllabus: {str(e)}. Please try again. 🚧")
    else:
        await query.edit_message_text("Syllabus not found. 🚧")

@handle_errors
async def toggle_reminders(update: Update, context):
    """Toggle reminders on or off"""
    progress = load_progress()
    
    # Toggle setting
    current_status = progress["global_settings"].get("reminders_enabled", True)
    progress["global_settings"]["reminders_enabled"] = not current_status
    save_progress(progress)
    
    # Inform user
    new_status = "enabled ✅" if progress["global_settings"]["reminders_enabled"] else "disabled ⏸️"
    await update.message.reply_text(f"Reminders are now {new_status}")

@handle_errors
async def set_reminder_interval(update: Update, context):
    """Set the number of days for each task"""
    if not context.args:
        await update.message.reply_text(
            "Please specify the number of days for each task. Example:\n"
            "/set_interval 10"
        )
        return
    
    try:
        days = int(context.args[0])
        if days < 1:
            await update.message.reply_text("Please use a positive number of days.")
            return
            
        progress = load_progress()
        progress["global_settings"]["reminder_interval"] = days
        
        # Update due date for current syllabus if one is active
        syllabi = load_syllabi()
        if syllabi["current_field"]:
            update_due_date(progress, syllabi["current_field"])
        
        save_progress(progress)
        await update.message.reply_text(f"Task interval set to {days} days! ⏱️")
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")

@handle_errors
async def show_statistics(update: Update, context):
    """Show simple statistics about the current syllabus progress"""
    syllabi = load_syllabi()
    progress = load_progress()
    
    if not syllabi["current_field"]:
        await update.message.reply_text("No active syllabus. Use /start to select one.")
        return
        
    current_field = syllabi["current_field"]
    
    if current_field not in syllabi["syllabi"]:
        await update.message.reply_text("Current syllabus not found. Use /start to select a valid syllabus.")
        return
        
    syllabus_progress = get_syllabus_progress(progress, current_field)
    
    # Gather statistics
    total_tasks = len(syllabi["syllabi"][current_field]["tasks"])
    completed_tasks = len(syllabus_progress["completed_weeks"])
    current_week = syllabus_progress["current_week"]
    
    # Calculate completion percentage
    completion_pct = (completed_tasks / total_tasks) * 100 if total_tasks > 0 else 0
    
    # Calculate days since started
    start_date = datetime.fromisoformat(syllabus_progress["start_date"]) if isinstance(syllabus_progress["start_date"], str) else syllabus_progress["start_date"]
    days_active = (datetime.now() - start_date).days
    
    # Calculate days left for current task
    days_left = "N/A"
    if "due_date" in syllabus_progress:
        due_date = datetime.fromisoformat(syllabus_progress["due_date"]) if isinstance(syllabus_progress["due_date"], str) else syllabus_progress["due_date"]
        days_left = (due_date - datetime.now()).days
        
    # Format the statistics message
    stats_message = (
        f"📊 Statistics for {current_field}\n\n"
        f"✅ Tasks completed: {completed_tasks}/{total_tasks} ({completion_pct:.1f}%)\n"
        f"📈 Current progress: Task {min(current_week, total_tasks)}/{total_tasks}\n"
        f"📆 Days since started: {days_active}\n"
    )
    
    if days_left != "N/A":
        status = "overdue" if days_left < 0 else "remaining"
        days_text = abs(days_left)
        stats_message += f"⏱️ Current task: {abs(days_left)} days {status}\n"
    
    # Add remaining tasks
    if current_week <= total_tasks:
        remaining_tasks = total_tasks - current_week + 1
        stats_message += f"🔜 Tasks remaining: {remaining_tasks}\n"
        
        # Estimate completion date - avoiding complex calculations that might fail
        if days_active > 0 and completed_tasks > 0:
            try:
                avg_days_per_task = days_active / completed_tasks if completed_tasks > 0 else progress["global_settings"].get("reminder_interval", 7)
                estimated_days_left = remaining_tasks * avg_days_per_task
                estimated_completion_date = datetime.now() + timedelta(days=estimated_days_left)
                stats_message += f"🗓️ Estimated completion: {estimated_completion_date.strftime('%Y-%m-%d')} (in {int(estimated_days_left)} days)\n"
            except Exception as e:
                # Skip this part if there's an error
                logger.error(f"Error calculating completion date: {str(e)}")
                pass
    
    # Send the statistics - without Markdown parsing to avoid errors
    await update.message.reply_text(stats_message)

# Button handling functions
async def handle_yes_response(update: Update, context):
    """Handle when user completes a task"""
    query = update.callback_query
    await query.answer()
    
    syllabi = load_syllabi()
    progress = load_progress()
    
    if not syllabi["current_field"]:
        await query.edit_message_text("No active syllabus. Use /start to select one.")
        return
        
    current_field = syllabi["current_field"]
    syllabus_progress = get_syllabus_progress(progress, current_field)
    
    try:
        # Get the current week index (0-based for array access)
        current_week = syllabus_progress["current_week"]
        current_week_index = current_week - 1
        
        # Add current week INDEX to completed weeks
        if current_week_index not in syllabus_progress["completed_weeks"]:
            syllabus_progress["completed_weeks"].append(current_week_index)
        
        # Record completion date and time
        now = datetime.now()
        if "completion_dates" not in syllabus_progress:
            syllabus_progress["completion_dates"] = {}
        syllabus_progress["completion_dates"][str(current_week_index)] = now.isoformat()
        
        # Move to next week
        syllabus_progress["current_week"] += 1
        
        # Update due date for next task
        update_due_date(progress, current_field)
        
        # Save progress
        save_progress(progress)
        
        # Check if this was the final task
        if syllabus_progress["current_week"] > len(syllabi['syllabi'][current_field]["tasks"]):
            await query.edit_message_text(
                f"🎉 Congratulations! You've completed the entire '{current_field}' syllabus! 🎓\n\n"
                f"Use /show_all_syllabi to choose another syllabus to work on."
            )
        else:
            # Get indices for completed task and next task
            completed_task_index = current_week_index
            next_task_index = syllabus_progress["current_week"] - 1
            
            # Make sure indices are valid
            if completed_task_index < 0 or completed_task_index >= len(syllabi['syllabi'][current_field]["tasks"]):
                completed_task_index = 0
            if next_task_index < 0 or next_task_index >= len(syllabi['syllabi'][current_field]["tasks"]):
                next_task_index = 0
            
            # Show completed task and next task with proper indices
            await query.edit_message_text(
                f"Great job! 🎉 You've completed:\n\n"
                f"{syllabi['syllabi'][current_field]['tasks'][completed_task_index]}\n\n"
                f"Now, move on to:\n\n"
                f"{syllabi['syllabi'][current_field]['tasks'][next_task_index]}\n\n"
                f"Due in {progress['global_settings'].get('reminder_interval', 7)} days. ⏳"
            )
    except Exception as e:
        await query.edit_message_text(f"Error updating progress: {str(e)}. Please try again.")

async def handle_no_response(update: Update, context):
    """Handle when user hasn't completed a task"""
    query = update.callback_query
    await query.answer()
    
    syllabi = load_syllabi()
    progress = load_progress()
    
    if not syllabi["current_field"]:
        await query.edit_message_text("No active syllabus. Use /start to select one.")
        return
        
    current_field = syllabi["current_field"]
    syllabus_progress = get_syllabus_progress(progress, current_field)
    current_week = syllabus_progress["current_week"]
    
    try:
        # Extend the due date by half the original interval (giving extra time)
        interval = progress["global_settings"].get("reminder_interval", 7)
        extension = max(3, interval // 2)  # At least 3 days, or half the interval
        
        if "due_date" in syllabus_progress:
            due_date = datetime.fromisoformat(syllabus_progress["due_date"])
            extended_date = due_date + timedelta(days=extension)
            syllabus_progress["due_date"] = extended_date.isoformat()
            save_progress(progress)
            
            days_until = (extended_date - datetime.now()).days
            
            await query.edit_message_text(
                f"No worries! 🚧 Keep working on:\n\n"
                f"{syllabi['syllabi'][current_field]['tasks'][current_week-1]}\n\n"
                f"Due date extended by {extension} days (now due in {days_until} days).\n"
                f"Use /check again when ready. ⏳"
            )
        else:
            await query.edit_message_text(
                f"No worries! 🚧 Keep working on:\n\n"
                f"{syllabi['syllabi'][current_field]['tasks'][current_week-1]}\n\n"
                f"Use /check again when ready. ⏳"
            )
    except Exception as e:
        await query.edit_message_text(f"Error updating due date: {str(e)}. Please try again.")

async def handle_reset_yes(update: Update, context):
    """Handle reset confirmation"""
    query = update.callback_query
    await query.answer()
    
    syllabi = load_syllabi()
    progress = load_progress()
    
    if not syllabi["current_field"]:
        await query.edit_message_text("No active syllabus. Use /start to select one.")
        return
        
    current_field = syllabi["current_field"]
    
    try:
        # Reset progress for this syllabus
        if "syllabi_progress" in progress and current_field in progress["syllabi_progress"]:
            progress["syllabi_progress"][current_field] = {
                "current_week": 1,
                "completed_weeks": [],
                "start_date": datetime.now().isoformat(),
                "due_date": (datetime.now() + timedelta(days=progress["global_settings"].get("reminder_interval", 7))).isoformat()
            }
            save_progress(progress)
            
            await query.edit_message_text(
                f"Progress reset! 🌱 Starting fresh with {current_field}:\n\n"
                f"{syllabi['syllabi'][current_field]['tasks'][0]}\n\n"
                f"Due in {progress['global_settings'].get('reminder_interval', 7)} days. Use /check when completed! 🚀"
            )
        else:
            await query.edit_message_text("No progress found to reset. Use /start to begin.")
    except Exception as e:
        await query.edit_message_text(f"Error resetting progress: {str(e)}. Please try again.")

async def handle_reset_no(update: Update, context):
    """Handle reset cancellation"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Reset cancelled! 🚫 Continue with your current progress.")

# Daily check function to run with a job queue
async def check_due_dates(context):
    """Check if any tasks are due and send reminders"""
    bot = context.bot
    progress = load_progress()
    syllabi = load_syllabi()
    
    # Skip if reminders are disabled
    if not progress["global_settings"].get("reminders_enabled", True):
        return
        
    # Skip if no active syllabus
    if not syllabi["current_field"] or syllabi["syllabi"][syllabi["current_field"]].get("paused", False):
        return
    
    current_field = syllabi["current_field"]
    syllabus_progress = get_syllabus_progress(progress, current_field)
    
    # Check if we have a due date
    if "due_date" in syllabus_progress:
        due_date = datetime.fromisoformat(syllabus_progress["due_date"])
        now = datetime.now()
        
        # Calculate days remaining
        days_remaining = (due_date - now).days
        
        # If due today or tomorrow, send a reminder
        if 0 <= days_remaining <= 1:
            current_week = syllabus_progress["current_week"]
            if current_week <= len(syllabi["syllabi"][current_field]["tasks"]):
                current_task = syllabi["syllabi"][current_field]["tasks"][current_week - 1]
                
                # Get the chat ID from context.job.data
                chat_id = context.job.data
                
                # Send reminder
                if days_remaining == 0:
                    message = (
                        f"⏰ **Reminder**: Your current task is due today!\n\n"
                        f"**{current_field}**: {current_task}\n\n"
                        f"Use /check to mark as completed."
                    )
                else:  # days_remaining == 1
                    message = (
                        f"📅 **Reminder**: Your current task is due tomorrow!\n\n"
                        f"**{current_field}**: {current_task}\n\n"
                        f"Use /check to mark as completed when you're done."
                    )
                
                await bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
        
        # If overdue, send a reminder every 3 days
        elif days_remaining < 0:
            # Check if we've sent a reminder recently (every 3 days)
            last_reminder = datetime.fromisoformat(progress["global_settings"].get("last_reminder", "2000-01-01T00:00:00"))
            if (now - last_reminder).days >= 3:
                current_week = syllabus_progress["current_week"]
                if current_week <= len(syllabi["syllabi"][current_field]["tasks"]):
                    current_task = syllabi["syllabi"][current_field]["tasks"][current_week - 1]
                    
                    # Get the chat ID
                    chat_id = context.job.data
                    
                    # Send overdue reminder
                    message = (
                        f"⚠️ **Task Overdue**: Your current task is {abs(days_remaining)} days overdue!\n\n"
                        f"**{current_field}**: {current_task}\n\n"
                        f"Use /check to mark as completed or /set_interval to adjust your schedule."
                    )
                    
                    await bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
                    
                    # Update last reminder time
                    progress["global_settings"]["last_reminder"] = now.isoformat()
                    save_progress(progress)

# Set up the reminder job
def setup_reminder_job(application, chat_id):
    """Set up the daily reminder check job"""
    if application.job_queue is None:
        logger.warning("Job queue is not available. Reminders will not be sent. Install with: pip install 'python-telegram-bot[job-queue]'")
        return
        
    application.job_queue.run_daily(
        check_due_dates,
        time=time(hour=10, minute=0),  # Send at 10:00 AM
        days=(0, 1, 2, 3, 4, 5, 6),  # Every day
        data=chat_id
    )

async def echo(update: Update, context):
    """Echo the user message. 🗣️"""
    await update.message.reply_text(f"You said: {update.message.text} 🎤\n\nUse /help to see available commands.")

async def button_handler(update: Update, context):
    """Handle button clicks. 🔘"""
    query = update.callback_query
    
    if query.data.startswith("start_"):
        await start_syllabus_callback(update, context)
    elif query.data.startswith("show_"):
        await show_syllabus_callback(update, context)
    elif query.data.startswith("switch_"):
        await switch_syllabus_callback(update, context)
    elif query.data.startswith("pause_"):
        await pause_syllabus_callback(update, context)
    elif query.data.startswith("resume_"):
        await resume_syllabus_callback(update, context)
    elif query.data == "yes":
        await handle_yes_response(update, context)
    elif query.data == "no":
        await handle_no_response(update, context)
    elif query.data == "reset_yes":
        await handle_reset_yes(update, context)
    elif query.data == "reset_no":
        await handle_reset_no(update, context)

# Global error handler
async def error_handler(update, context):
    """Log errors and send a message to the developer."""
    logger.error(f"Exception while handling an update: {context.error}")
    logger.error(traceback.format_exc())
    
    # Try to notify the user
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "Sorry, an error occurred. Please try again or use /help."
        )

def main():
    """Start the bot. 🚀"""
    application = Application.builder().token(BOT_TOKEN).build()

    # Add handlers 🎛️
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("current", current_week))
    application.add_handler(CommandHandler("completed", show_completed))
    application.add_handler(CommandHandler("check", check_progress))
    application.add_handler(CommandHandler("reset", reset_progress))
    application.add_handler(CommandHandler("show_all_syllabi", show_all_syllabi))
    application.add_handler(CommandHandler("switch_syllabus", switch_syllabus))
    application.add_handler(CommandHandler("pause_syllabus", pause_syllabus))
    application.add_handler(CommandHandler("resume_syllabus", resume_syllabus))
    application.add_handler(CommandHandler("toggle_reminders", toggle_reminders))
    application.add_handler(CommandHandler("set_interval", set_reminder_interval))
    application.add_handler(CommandHandler("statistics", show_statistics))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Set up reminder for your chat ID (replace with your actual Telegram ID)
    YOUR_CHAT_ID = 123456789  # Replace with your actual Telegram ID
    setup_reminder_job(application, YOUR_CHAT_ID)

    # Start the Bot 🎬
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()