# **Distributed Polling System**

## **Setup Instructions**

Follow the steps below to set up and run the Distributed Polling System:

---

### **Prerequisites**

Ensure the following dependencies are installed on your machine:
- **Python** (version 3.10 or higher recommended)
- **Docker** (for RabbitMQ setup)
- **Nginx**

---

### **Steps to Run**

1. Ensure all requirements are installed from the requirements.txt file - `pip3 install -r requirements.txt`

2. **Start RabbitMQ**:  
   Run the RabbitMQ container using Docker with default settings:
   ```bash
   docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:management

3. Start Nginx:
    Ensure Nginx is running and configured to listen on port 9000 using the provided Nginx configuration file.

4. Run the subscriber `python3 subscriber.py`

5. Run the webservers `python3 server1.py` `python3 server2.py`

6. Navigate to http://localhost:9001, login as admin with username:`admin`, password: `admin`
