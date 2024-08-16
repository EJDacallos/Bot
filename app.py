from flask import Flask, render_template, request, jsonify
from threading import Thread, Event
import time
import random
from instagrapi import Client
from datetime import datetime


app = Flask(__name__)

# Global variables to control the bot and store notifications
stop_events = {}
pause_events = {}
bot_threads = {}
notifications = []
activity_log = []

# Function to convert hours, minutes, and seconds to total seconds
def convert_to_seconds(hours, minutes, seconds):
    return hours * 3600 + minutes * 60 + seconds

# Function to add a notification
def add_notification(message):
    global notifications
    notifications.append(message)
    if len(notifications) > 100:  # Keep the last 100 messages
        notifications.pop(0)

# Function to log activity with a timestamp
def log_activity(data):
    global activity_log
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    data['timestamp'] = timestamp
    activity_log.append(data)
    if len(activity_log) > 100:  # Keep the last 100 logs
        activity_log.pop(0)

# Function to run the Instagram bot
def run_bot(username, password, target_type, target_values, max_likes, like_min_interval, like_max_interval, cycle_interval, run_duration, comment_text, follow_unfollow, stop_event, pause_event):
    liked_comments = set()
    stop_event.clear()
    pause_event.set()  # Initially, the bot is not paused

    # Initialize the Instagram Client
    cl = Client()
    cl.login(username, password)

    if target_type == 'username':
        user_id = cl.user_id_from_username(target_values[0])
        get_posts = lambda: cl.user_medias(user_id, 5)
    elif target_type == 'hashtag':
        get_posts = lambda: cl.hashtag_medias_top(random.choice(target_values), amount=5)
    else:
        raise ValueError("Invalid target type. Choose 'username' or 'hashtag'.")

    end_time = time.time() + run_duration
    newly_liked_comments = []

    while not stop_event.is_set() and time.time() < end_time:
        posts = get_posts()
        likes = 0

        for post in posts:
            if stop_event.is_set() or likes >= max_likes:
                break

            comments = cl.media_comments(post.pk)
            new_comments = [comment for comment in comments if comment.pk not in liked_comments]
            new_comments.sort(key=lambda c: c.created_at_utc, reverse=True)

            for comment in new_comments:
                if stop_event.is_set() or likes >= max_likes:
                    break

                pause_event.wait()
                try:
                    cl.comment_like(comment.pk)
                    liked_comments.add(comment.pk)
                    newly_liked_comments.append(comment)
                    likes += 1
                    random_interval = random.uniform(like_min_interval, like_max_interval)
                    time.sleep(random_interval)
                except Exception as e:
                    add_notification(f"{e}: {comment.text}")

        if not stop_event.is_set() and time.time() < end_time:
            if comment_text:
                for post in posts:
                    try:
                        cl.media_comment(post.pk, comment_text)
                        add_notification(f"You commented: '{comment_text}' on a post by {target_values}")
                    except Exception as e:
                        add_notification(f"Failed to comment: {e}")

            if follow_unfollow:
                for post in posts:
                    user_id = post.user.pk
                    if follow_unfollow == "follow":
                        try:
                            cl.user_follow(user_id)
                            add_notification(f"You followed {post.user.username}")
                        except Exception as e:
                            add_notification(f"Failed to follow: {e}")
                    elif follow_unfollow == "unfollow":
                        try:
                            cl.user_unfollow(user_id)
                            add_notification(f"You unfollowed {post.user.username}")
                        except Exception as e:
                            add_notification(f"Failed to unfollow: {e}")

            time.sleep(cycle_interval)

    for comment in newly_liked_comments:
        add_notification(f"You liked the comment: {comment.text}")

    add_notification(f"Bot for {username} stopped or finished.")

@app.route('/', methods=['GET', 'POST'])
def index():
    global bot_threads, stop_events, pause_events, activity_log, notifications

    if request.method == 'POST':
        if 'start' in request.form:
            username = request.form['username']
            password = request.form['password']
            target_type = request.form['target_type']
            target_value = request.form['target_value']
            max_likes = int(request.form['max_likes'])

            like_min_interval = convert_to_seconds(
                int(request.form['like_min_interval_hours']),
                int(request.form['like_min_interval_minutes']),
                int(request.form['like_min_interval_seconds'])
            )

            like_max_interval = convert_to_seconds(
                int(request.form['like_max_interval_hours']),
                int(request.form['like_max_interval_minutes']),
                int(request.form['like_max_interval_seconds'])
            )

            cycle_interval = convert_to_seconds(
                int(request.form['cycle_interval_hours']),
                int(request.form['cycle_interval_minutes']),
                int(request.form['cycle_interval_seconds'])
            )

            run_duration = convert_to_seconds(
                int(request.form['run_duration_hours']),
                int(request.form['run_duration_minutes']),
                int(request.form['run_duration_seconds'])
            )

            comment_text = request.form['comment_text']
            follow_unfollow = request.form['follow_unfollow']

            if target_type == 'hashtag':
                target_value = target_value.split(',')
            else:
                target_value = [target_value]

            activity_data = {
                "username": username,
                "target_type": target_type,
                "target_value": target_value,
                "max_likes": max_likes,
                "like_min_interval": like_min_interval,
                "like_max_interval": like_max_interval,
                "cycle_interval": cycle_interval,
                "run_duration": run_duration,
                "comment_text": comment_text,
                "follow_unfollow": follow_unfollow
            }

            activity_data['like_min_interval_hms'] = f"{int(like_min_interval // 3600)}h {int((like_min_interval % 3600) // 60)}m {int(like_min_interval % 60)}s"
            activity_data['like_max_interval_hms'] = f"{int(like_max_interval // 3600)}h {int((like_max_interval % 3600) // 60)}m {int(like_max_interval % 60)}s"
            activity_data['cycle_interval_hms'] = f"{int(cycle_interval // 3600)}h {int((cycle_interval % 3600) // 60)}m {int(cycle_interval % 60)}s"
            activity_data['run_duration_hms'] = f"{int(run_duration // 3600)}h {int((run_duration % 3600) // 60)}m {int(run_duration % 60)}s"

            log_activity(activity_data)

            if username not in bot_threads or not bot_threads[username].is_alive():
                stop_events[username] = Event()
                pause_events[username] = Event()
                pause_events[username].set()
                bot_thread = Thread(
                    target=run_bot,
                    args=(username, password, target_type, target_value, max_likes, like_min_interval, like_max_interval, cycle_interval, run_duration, comment_text, follow_unfollow, stop_events[username], pause_events[username])
                )
                bot_threads[username] = bot_thread
                bot_thread.start()

        elif 'stop' in request.form:
            username = request.form['username']
            if username in stop_events:
                stop_events[username].set()
                if username in bot_threads:
                    bot_threads[username].join()

        elif 'pause' in request.form:
            username = request.form['username']
            if username in pause_events:
                pause_events[username].clear()

        elif 'resume' in request.form:
            username = request.form['username']
            if username in pause_events:
                pause_events[username].set()

    return render_template('index.html', activity_log=activity_log, notifications=notifications, bot_info={
        'running': {username: thread.is_alive() for username, thread in bot_threads.items()},
        'paused': {username: not pause_event.is_set() for username, pause_event in pause_events.items()}
    })

if __name__ == '__main__':
    app.run(debug=True)
