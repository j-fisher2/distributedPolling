import sqlite3
import pika
import threading
import json
import hashlib
import re

DATABASES = ["./databases/db1.sqlite", "./databases/db2.sqlite", "./databases/db3.sqlite"]

def get_shard_based_on_username(username):
    hash_value = int(hashlib.sha256(username.encode()).hexdigest(), 16)
    return hash_value % len(DATABASES)

def get_userID_from_username(db_names, username):
    for db in db_names: 
        try:
            conn = sqlite3.connect(db)
            cursor = conn.cursor()
            cursor.execute("SELECT ID FROM Users WHERE username = ?", (username,))
            result = cursor.fetchone() 
            
            conn.close() 
            
            if result: 
                return result[0]
            else:
                print(f"No user ID found for username '{username}' in database '{db}'.")
        except Exception as e:
            print(f"Failed to query database '{db}': {e}")
        finally:
            if 'conn' in locals():  
                conn.close()
    
    return None
        

def initialize_database(db_name):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS Votes (userID INTEGER NOT NULL, topicID INTEGER NOT NULL, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, response TEXT NOT NULL, PRIMARY KEY(userID,topicID), FOREIGN KEY (userID) REFERENCES Users(ID),FOREIGN KEY (topicID) REFERENCES Topic(ID))")
    cursor.execute("CREATE TABLE IF NOT EXISTS Users (ID INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL, createdAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cursor.execute("CREATE TABLE IF NOT EXISTS Topic (ID INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, description TEXT NOT NULL, createdAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cursor.execute("CREATE TABLE IF NOT EXISTS RequestedVotes (ID INTEGER PRIMARY KEY, username TEXT NOT NULL, createdAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP, topicID INTEGER NOT NULL, FOREIGN KEY(topicID) REFERENCES Topic(ID))")
    cursor.execute("""
        INSERT INTO Users (username, password, role) 
        SELECT 'admin', 'admin', 'admin'
        WHERE NOT EXISTS (
            SELECT 1 FROM Users WHERE username = 'admin'
        )
    """)
    conn.commit()
    conn.close()

def sanitize_text(text, max_length=255, allow_special=False):
    if len(text) > max_length:
        raise ValueError(f"Text exceeds maximum allowed length of {max_length}.")
    if not allow_special:
        # Remove characters that are not alphanumeric, spaces, or basic punctuation
        text = re.sub(r'[^a-zA-Z0-9\s.,!?-]', '', text)
    return text.strip()

def write_vote_to_database(db_names, topicID,username, response, voteID, quorum = 2):
    successful_writes = 0
    userID = get_userID_from_username(db_names,username)
    response = sanitize_text(response)
    if not userID:
        return False
    for db in db_names:
        try:
            conn = sqlite3.connect(db)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO votes (topicID, userID, response) VALUES (?, ?, ?)", (topicID, userID, response))
            conn.commit()
            cursor.execute("DELETE FROM RequestedVotes WHERE username = ? AND topicID = ?",(username,topicID))
            conn.commit()
            successful_writes += 1
            print(f"Successfully wrote to {db}")
        except Exception as e:
            print(f"Failed to write to {db}: {e}")
        finally:
            conn.close()

    return successful_writes == quorum

def write_topic_to_database(name,description, quorum = 3):
    successful_writes = 0
    name = sanitize_text(name)
    description = sanitize_text(description)
    for db in DATABASES:
        try:
            conn = sqlite3.connect(db)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO Topic (name, description) VALUES (?, ?)", (name, description))
            conn.commit()
            conn.close()
            successful_writes += 1
            print(f"Successfully wrote to {db}")
        except Exception as e:
            print(f"Failed to write to {db}: {e}")
        finally:
            conn.close()

    return successful_writes == quorum

def write_user_to_database(username,password, role = "voter", quorum = 2):
    username = sanitize_text(username)
    successful_writes = 0
    db_shard = get_shard_based_on_username(username)
    db_shard2 = (db_shard+1)%len(DATABASES)
    databases = [DATABASES[db_shard],DATABASES[db_shard2]]
    print(databases)
    for db in databases:
        try:
            conn = sqlite3.connect(db)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO Users (username, password, role) VALUES (?, ?, ?)", (username, password, role))
            conn.commit()
            conn.close()
            successful_writes += 1
            print(f"Successfully wrote user to {db}")
        except Exception as e:
            print(f"Failed to write to {db}: {e}")
        finally:
            conn.close()

    return successful_writes == quorum

def write_vote_request(username,topicID, quorum = 2):
    successful_writes = 0
    db_shard = get_shard_based_on_username(username)
    db_shard2 = (db_shard+1)%len(DATABASES)
    databases = [DATABASES[db_shard],DATABASES[db_shard2]]
    print(databases)
    for db in databases:
        try:
            conn = sqlite3.connect(db)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO RequestedVotes (username, topicID) VALUES (?, ?)", (username, topicID))
            conn.commit()
            conn.close()
            successful_writes += 1
            print(f"Successfully wrote user to {db}")
        except Exception as e:
            print(f"Failed to write to {db}: {e}")
        finally:
            conn.close()

    return successful_writes == quorum


def subscriber_worker(db_name):
    connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()
    queues = ['votes', 'create-voting-topic', 'create-user-topic','create-user-vote-request']
    for queue in queues:
        channel.queue_declare(queue=queue)

    def callback(ch, method, properties, body):
        try:
            data = json.loads(body.decode())
            print(f"Message received from queue: {method.routing_key}")
            
            if method.routing_key == 'votes':
                print(data)
                topicID = data.get("topicID")
                username = data.get("username")
                response = data.get("response")
                voteID = data.get("voteID")

                if not topicID or not username or not response or not voteID:
                    print(f"Invalid message data: {data}")
                    return
                print(data,topicID,username,response,voteID)

                db_shard = get_shard_based_on_username(username)
                db_shard2 = (db_shard+1)%len(DATABASES)
                targetted_databases = [DATABASES[db_shard],DATABASES[db_shard2]]
                print(targetted_databases)
                if write_vote_to_database(targetted_databases, topicID, username, response, voteID):
                    print(f"Vote for '{topicID}' written to {db_name}")
                else:
                    print(f"Failed to meet quorum for vote on '{topicID}'.")

            elif method.routing_key == 'create-voting-topic':
                name = data.get("name")
                description = data.get("description")
                
                if not name or not description:
                    print(f"Invalid message data: {data}")
                print(data)

                if write_topic_to_database(name,description):
                    print(f"Topic '{name}' written to databases")
                else:
                    print("Failed to meet quorum on topic write.")
            
            elif method.routing_key == 'create-user-topic':
                username = data.get("username")
                password = data.get("password")
                role = data.get("role")
                
                if not username or not password or not role:
                    print(f"Invalid message data: {data}")
                print(data)

                if write_user_to_database(username,password,role):
                    print(f"User'{username}' written to databases")
                else:
                    print("Failed to meet quorum on topic write.")
            
            elif method.routing_key == 'create-user-vote-request':
                username = data.get("username")
                topicID = data.get("topicID")

                if not username or not topicID:
                    print(f"Invalid message data: {data}")
                print(data)

                if write_vote_request(username,topicID):
                    print(f"User vote request for'{username}' written to databases")
                else:
                    print("Failed to meet quorum on topic write.")


        except Exception as e:
            print(f"Error in callback processing: {e}")

    for queue in queues:
        channel.basic_consume(queue=queue, on_message_callback=callback, auto_ack=True)

    print(f"Subscriber listening for messages on {', '.join(queues)}")
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        print("Subscriber stopped.")
        connection.close()

if __name__ == "__main__":
    for db in DATABASES:
        initialize_database(db)
        threading.Thread(target=subscriber_worker, args=(db,)).start()
