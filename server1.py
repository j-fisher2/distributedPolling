from flask import Flask, request, jsonify, render_template, redirect, url_for, make_response,flash
import pika
from flask_cors import CORS
import json
import requests
import sqlite3
import hashlib
import jwt
import datetime

app = Flask(__name__)
CORS(app)
app.secret_key = "key2"

SECRET_KEY = "test_key"

def publish_to_votes_queue(topicID, username, response, voteID):
    connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()
    channel.queue_declare(queue='votes')
    message = json.dumps({"topicID": topicID, "username": username, "response": response, "voteID":voteID})
    channel.basic_publish(exchange='', routing_key='votes', body=message)
    connection.close()

def publish_to_create_topic_queue(name,description):
    connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()
    channel.queue_declare(queue='create-voting-topic')
    message = json.dumps({"name": name, "description": description})
    channel.basic_publish(exchange='', routing_key='create-voting-topic', body=message)
    connection.close()

def publish_to_create_user_queue(username,password, role="voter"):
    connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()
    channel.queue_declare(queue='create-user-topic')
    message = json.dumps({"username": username, "password": password,"role":role})
    channel.basic_publish(exchange='', routing_key='create-user-topic', body=message)
    connection.close()

def publish_to_create_user_vote_request(username, topicID):
    connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()
    channel.queue_declare(queue='create-user-vote-request')
    message = json.dumps({"username": username, "topicID": topicID })
    channel.basic_publish(exchange='', routing_key='create-user-vote-request', body=message)
    connection.close()

DATABASES = ["./databases/db1.sqlite", "./databases/db2.sqlite", "./databases/db3.sqlite"]

def get_shard_based_on_username(username):
    hash_value = int(hashlib.sha256(username.encode()).hexdigest(), 16)
    return hash_value % len(DATABASES)

def generate_user_token(username, role='voter'):
    """
    Generates a JWT token for the user with an expiration time.
    :param username: The username of the logged-in user
    :return: Encoded JWT token
    """
    payload = {
        'username': username,
        'role': role,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=1)  # Token expires in 1 hour
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')  
    return token if isinstance(token, str) else token.decode('utf-8')

def decode_user_token(token):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return {"error": "Token has expired"}
    except jwt.InvalidTokenError:
        return {"error": "Invalid token"}
    
def valid_token(token,role):
    token = decode_user_token(token)
    if token and token['role'] == role:
        return True
    return False

def get_all_topics():
    try:
        conn = sqlite3.connect(DATABASES[0])
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Topic")
        results = cursor.fetchall()
        return results
    except: 
        return []
    finally:
        if 'conn' in locals():  
                conn.close()

def get_all_votes():
    unique_votes = set() 

    try:
        for db in DATABASES:
            conn = sqlite3.connect(db) 
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM Votes")  # Query the Votes table
            results = cursor.fetchall()  # Fetch all rows

            for vote in results:
                userID, topicID, timestamp, response = vote
                unique_votes.add((userID, topicID, timestamp, response))  

        return list(unique_votes)  
    except sqlite3.Error as e:
        print(f"Error occurred: {e}")
        return None
    
    finally:
        conn.close()  # Close the database connection

def get_users():
    unique_users = set() 

    try:
        for db in DATABASES:
            conn = sqlite3.connect(db) 
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM Users")  # Query the Votes table
            results = cursor.fetchall()  # Fetch all rows

            for user in results:
                ID, username, password, role, createdAt = user
                unique_users.add((ID, username, password, role, createdAt))  

        return list(unique_users)  
    except sqlite3.Error as e:
        print(f"Error occurred: {e}")
        return None
    
    finally:
        conn.close()  # Close the database connection


def get_pending_votes(username):
    shard = get_shard_based_on_username(username)
    db = DATABASES[shard]
    results = []  

    query = """
    SELECT RequestedVotes.username, RequestedVotes.ID,RequestedVotes.createdAT,RequestedVotes.topicID, Topic.description
    FROM RequestedVotes
    JOIN Topic ON RequestedVotes.topicID = Topic.ID
    WHERE RequestedVotes.username = ?
    """

    try:
        conn = sqlite3.connect(db)
        cursor = conn.cursor()
        cursor.execute(query, (username,))
        
        rows = cursor.fetchall()
        
        if rows:
            results = [list(row) for row in rows] 

        return json.dumps(results)  # Convert the list to JSON string

    except Exception as e:
        print(f"Error with primary database: {e}. Retrying with next shard...")
        next_shard = (shard + 1) % len(DATABASES)
        db = DATABASES[next_shard]

        try:
            conn = sqlite3.connect(db)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM RequestedVotes WHERE username = ?", (username,))
            
            # Fetch all rows from the second database
            rows = cursor.fetchall()
            
            if rows:
                results = [list(row) for row in rows]  # Convert each row to a list

            return json.dumps(results)  # Return as JSON string

        except Exception as e:
            print(f"Error with secondary database: {e}")
            return json.dumps([])  # Return an empty JSON array if both fail

    finally:
        if conn:
            conn.close()  # Ensure the connection is closed properly

#vote endpoint
@app.route('/vote', methods=['GET','POST'])
def handle_vote():
    if request.method == 'GET':
        username, voteID,topicID, topic = request.args.get('username'),request.args.get('voteID'),request.args.get('topicID'),request.args.get('topic')
        return render_template('cast_vote.html',username=username,voteID=voteID,topicID=topicID,topic=topic)
    elif request.method == 'POST':
        try:
      
            topicID = request.form.get("topicID")
            username = request.form.get("username")
            response = request.form.get("vote")
            voteID = request.form.get("voteID")

            if not topicID or not username or not response or not voteID:
                return jsonify({
                    "error": "Missing required fields",
                    "details": {
                        "topicID": topicID,
                        "username": username,
                        "response": response
                    }
                }), 400

            # Publish to RabbitMQ
            try:
                print(topicID,username,response)
                publish_to_votes_queue(topicID, username, response, voteID)
            except Exception as pub_err:
                print(f"Error in publish_to_queue: {pub_err}")
                return jsonify({"error": "Failed to queue vote"}), 500

            return render_template('success_vote.html',username=username,voteID=voteID,topicID=topicID), 200
        except Exception as e:
            print(f"Unexpected error in handle_vote: {e}")
            return jsonify({"error": "Internal server error"}), 500

def valid_credentials(username, password, role="voter"):
    try:
        shard = get_shard_based_on_username(username)
        conn = sqlite3.connect(DATABASES[shard])
        cursor = conn.cursor()
        cursor.execute("SELECT password,role FROM Users WHERE username = ?",(username,))
        results = cursor.fetchone()
        if results[0] == password and results[1] == role:
            return True
        return False
    except: 
        return []
    finally:
        if 'conn' in locals():  
                conn.close()

def valid_invite(username,password):
    return True

@app.route('/')
def home():
    return render_template('home.html', server = "server1")

@app.route('/logout')
def logout():
    response = make_response(redirect(url_for('home')))
    response.set_cookie('auth_token', '', expires=0, httponly=True, secure=False) 
    return response


@app.route("/home/<username>")
def user_home(username):
    token = request.cookies.get('auth_token')
    if not token:
        return jsonify({"message": "unauthorized"})
    if not valid_token(token,"voter"):
        return jsonify({"message": "unauthorized"})
    return render_template("userhome.html", username=username)

@app.route("/admin-view-topics/<username>")
def admin_view_topics(username):
    token = request.cookies.get('auth_token')
    if not token:
        return jsonify({"message": "unauthorized"})
    if not valid_token(token,"admin"):
        return jsonify({"message": "unauthorized"})
    results1 = get_all_topics() #topics: [ID INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, description TEXT NOT NULL, createdAt]
    results2 = get_all_votes() #votes: [userID INTEGER NOT NULL, topicID INTEGER NOT NULL, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, response]
    correlated_data = []
    for topic in results1:
        topic_votes = [vote for vote in results2 if vote[1] == topic[0]]
        correlated_data.append({
            "topicID": topic[0],
            "name": topic[1],
            "description": topic[2],
            "createdAt": topic[3],
            "votes": topic_votes
        })
    print(correlated_data)
    return render_template("view_all_topic_data.html", correlated_data=correlated_data, username=username)

@app.route("/admin-home/<username>")
def admin_home(username):
    token = request.cookies.get('auth_token')
    if not token:
        return jsonify({"message": "unauthorized"})
    if not valid_token(token,"admin"):
        return jsonify({"message": "unauthorized"})
    return render_template("admin_home.html", username=username)

@app.route("/admin-view-users/<username>")
def list_users(username):
    token = request.cookies.get('auth_token')
    if not token:
        return jsonify({"message": "unauthorized"})
    if not valid_token(token,"admin"):
        return jsonify({"message": "unauthorized"})
    users = get_users()
    print(users)
    return render_template('user_list.html', users=users,username=username)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template("login.html")
    elif request.method == 'POST':
        username = request.form.get("username")
        password = request.form.get("password")
        
        if not username or not password:
            return jsonify({"error": "Missing username or password"}), 400

        if valid_credentials(username, password):
            token = generate_user_token(username)
            print(token)
            response = make_response(redirect(url_for('user_home', username=username)))
            response.set_cookie('auth_token', token, httponly=True, secure=False)  # Secure=True for HTTPS
            return response

        return render_template('login.html',error="Invalid username or password. Please try again.")

@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'GET':
        return render_template("admin_login.html")
    elif request.method == 'POST':
        username = request.form.get("username")
        password = request.form.get("password")
        
        if not username or not password:
            return jsonify({"error": "Missing username or password"}), 400

        if valid_credentials(username, password,"admin"):
            token = generate_user_token(username,'admin')
            print(token)
            response = make_response(redirect(url_for('admin_home', username=username)))
            response.set_cookie('auth_token', token, httponly=True, secure=False)  # Secure=True for HTTPS
            return response
        
        return render_template('admin_login.html', error="Invalid username or password. Please try again.")

@app.route('/invite/<username>', methods=['GET'])
def invite(username):
    token = request.cookies.get('auth_token')
    if not token:
        return jsonify({"message": "unauthorized"})
    if not valid_token(token,"admin"):
        return jsonify({"message": "unauthorized"})
    if request.method == 'GET':
        return render_template("invite_user.html",username=username)

@app.route('/request-vote/<username>')
def request_vote(username):
    token = request.cookies.get('auth_token')
    if not token:
        return jsonify({"message": "unauthorized"})
    if not valid_token(token,"admin"):
        return jsonify({"message": "unauthorized"})
    return render_template('request_voter_admin.html',username=username)

@app.route('/requested-votes')
def requested_votes():
    token = request.cookies.get('auth_token')
    if not token:
        return jsonify({"message": "unauthorized"})
    if not valid_token(token,"voter"):
        return jsonify({"message": "unauthorized"})
    username = request.args.get('username')

    pending_votes = get_pending_votes(username)
    print(pending_votes)

    if pending_votes:  
        votes = json.loads(pending_votes)  
    else:
        votes = []  

    return render_template("requested_votes.html", username=username, votes=votes)

@app.route('/create-topic/<username>', methods=['GET', 'POST'])
def create_topic_page(username):
    token = request.cookies.get('auth_token')
    if not token:
        return jsonify({"message": "unauthorized"})
    if not valid_token(token,"admin"):
        return jsonify({"message": "unauthorized"})

    if request.method == 'GET':
        return render_template("create_topic.html",username=username)

    elif request.method == 'POST':
        try:
            data = request.json
            if data is None:
                return jsonify({"error": "Invalid JSON"}), 400
            print(data)
            # Validate required fields
            name = data.get("name")
            description = data.get("description")

            if not name or not description:
                return jsonify({
                    "error": "Missing required fields",
                    "details": {
                        "name": name,
                        "description": description
                    }
                }), 400

            # Publish to RabbitMQ
            publish_to_create_topic_queue(name, description)
            return jsonify({"status": "Topic created successfully"}), 200

        except Exception as e:
            print(f"Unexpected error in create_topic_page: {e}")
            return jsonify({"error": "Internal server error"}), 500

@app.route('/create-user', methods=['POST'])
def create_user_page():
    token = request.cookies.get('auth_token')
    if not token:
        return jsonify({"message": "unauthorized"})
    if not valid_token(token,"admin"):
        return jsonify({"message": "unauthorized"})

    try:
        data = request.json
        if data is None:
            return jsonify({"error": "Invalid JSON"}), 400

        # Validate required fields
        username,password,role = data.get("username"),data.get("password"),data.get("role")
        print(username,password,role)

        if not username or not password or not role:
            return jsonify({
                "error": "Missing required fields",
                "details": {
                    "username": username,
                    "password": password
                }
            }), 400

        # Publish to RabbitMQ
        publish_to_create_user_queue(username, password,role)
        return jsonify({"status": "User created successfully"}), 200

    except Exception as e:
        print(f"Unexpected error in create_user_page: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route('/create-user-vote-request', methods=['POST'])
def create_user_vote_request():
        token = request.cookies.get('auth_token')
        if not token:
            return jsonify({"message": "unauthorized"})
        if not valid_token(token,"admin"):
            return jsonify({"message": "unauthorized"})
        try:
            data = request.json
            if data is None:
                return jsonify({"error": "Invalid JSON"}), 400

            # Validate required fields
            username,topicID = data.get("username"),data.get("topicID")
            print(username,topicID)

            if not username or not topicID:
                return jsonify({
                    "error": "Missing required fields",
                    "details": {
                        "username": username,
                        "topicID": topicID
                    }
                }), 400

            # Publish to RabbitMQ
            publish_to_create_user_vote_request(username, topicID)
            return jsonify({"status": "User vote request created successfully"}), 200

        except Exception as e:
            print(f"Unexpected error in create_user_page: {e}")
            return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
