# CLIENT

import tkinter as tk
from tkinter import messagebox
import socket
import threading

class QuizClient:
    def __init__(self, master: tk.Tk):
        self.master = master
        master.title("Quiz - Client")
        master.grid_columnconfigure(index=list(range(4)), weight=1)
        master.grid_rowconfigure(index=list(range(6)), weight=1)

        self.client_socket = None
        self.is_connected = False
        self.listen_thread = None # The thread that will listen to the server for messages

        # Chosen answer, default at start is "A"
        self.answer_var = tk.StringVar(value="A")

        self.create_widgets()
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

    # Create the GUI
    def create_widgets(self):
        # Connection Frame (includes IP, Port and Name fields)
        conn = tk.Frame(self.master)
        conn.grid(row=0, column=0, columnspan=4, padx=10, pady=10, sticky="NWSE")
        conn.grid_columnconfigure(index=list(range(6)), weight=1)

        # IP Entry Field
        tk.Label(conn, text="Server IP:").grid(row=0, column=0, sticky="E")
        self.ip_entry = tk.Entry(conn)
        self.ip_entry.grid(row=0, column=1, sticky="WE")

        # Port Entry Field
        tk.Label(conn, text="Port:").grid(row=0, column=2, sticky="E")
        self.port_entry = tk.Entry(conn)
        self.port_entry.grid(row=0, column=3, sticky="WE")

        # Name Entry Field
        tk.Label(conn, text="Name:").grid(row=0, column=4, sticky="E")
        self.name_entry = tk.Entry(conn)
        self.name_entry.grid(row=0, column=5, sticky="WE")

        # Connect Button
        self.connect_button = tk.Button(self.master, text="Connect", command=self.toggle_connection)
        self.connect_button.grid(row=1, column=0, columnspan=2, padx=10, sticky="WE")

        # Disconnect Button
        self.disconnect_button = tk.Button(self.master, text="Disconnect", command=self.disconnect)
        self.disconnect_button.grid(row=1, column=2, columnspan=2, padx=10, sticky="WE")
        self.disconnect_button.config(state=tk.DISABLED) # Disabled on start

        # Activity log (Listbox + Scrollbar)
        log_frame = tk.Frame(self.master)
        log_frame.grid(row=2, column=0, columnspan=4, rowspan=3, padx=10, pady=10, sticky="NWSE")
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)

        self.log_list = tk.Listbox(log_frame, height=15)
        self.log_list.grid(row=0, column=0, sticky="NWSE")

        sb = tk.Scrollbar(log_frame, orient="vertical")
        sb.grid(row=0, column=1, sticky="NS")
        self.log_list.config(yscrollcommand=sb.set)
        sb.config(command=self.log_list.yview)

        # Question Box
        self.q_text = tk.Text(self.master, height=6, state=tk.DISABLED) # Disabled at start
        self.q_text.grid(row=5, column=0, columnspan=4, padx=10, pady=5, sticky="NWSE")

        # Answer Options (Radio Buttons)
        rb_frame = tk.Frame(self.master)
        rb_frame.grid(row=6, column=0, columnspan=4, padx=10, pady=5, sticky="NWSE")
        rb_frame.grid_columnconfigure(index=list(range(3)), weight=1)

        self.rb_a = tk.Radiobutton(rb_frame, text="A", variable=self.answer_var, value="A")
        self.rb_b = tk.Radiobutton(rb_frame, text="B", variable=self.answer_var, value="B")
        self.rb_c = tk.Radiobutton(rb_frame, text="C", variable=self.answer_var, value="C")

        self.rb_a.grid(row=0, column=0, sticky="N")
        self.rb_b.grid(row=0, column=1, sticky="N")
        self.rb_c.grid(row=0, column=2, sticky="N")

        # Submit Button
        self.submit_button = tk.Button(self.master, text="Submit Answer", command=self.submit_answer)
        self.submit_button.grid(row=7, column=0, columnspan=4, padx=10, pady=10, sticky="WE")
        self.submit_button.config(state=tk.DISABLED) # Disabled until a question comes to avoid errors

        # Adjust weights of rows for better visual clarity
        self.master.grid_rowconfigure(2, weight=5) # Message log
        self.master.grid_rowconfigure(5, weight=1) # Question box
        self.master.grid_rowconfigure(6, weight=0) # Radio buttons
        self.master.grid_rowconfigure(7, weight=0) # Submit button


    # Helper function that logs the message into the activity log
    def log(self, msg: str):
        self.log_list.insert(tk.END, msg)
        self.log_list.yview(tk.END)

    # Helper function that prints the incoming question to the question box
    def set_question_display(self, msg: str):
        self.q_text.config(state=tk.NORMAL)
        self.q_text.delete("1.0", tk.END)
        self.q_text.insert(tk.END, msg)
        self.q_text.config(state=tk.DISABLED)

    # Connection Logic
    def toggle_connection(self):
        if self.is_connected:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        # Get the values from entry fields
        ip = self.ip_entry.get().strip()
        port_str = self.port_entry.get().strip()
        name = self.name_entry.get().strip()

        # If any necessery fields are left empty
        if not ip or not port_str or not name:
            messagebox.showerror("Error", "IP, Port, and Name must be filled.")
            return

        try:
            port = int(port_str)
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((ip, port))
            self.is_connected = True

            # Send name first to if it's a duplicate
            self.client_socket.sendall(name.encode())

            # Create the thread that will watch for incoming messages from the server
            self.listen_thread = threading.Thread(target=self.receive_loop, daemon=True)
            self.listen_thread.start()

            self.connect_button.config(state=tk.DISABLED)
            self.disconnect_button.config(state=tk.NORMAL)

            self.log("CONNECTED to "+ ip + ":" + str(port) + " as '" + name + "'")
            self.log("Waiting for server messages...")

        except (socket.error, ValueError) as e:
            messagebox.showerror("Connection Error", f"Could not connect: {e}")
            self.is_connected = False
            try:
                if self.client_socket:
                    self.client_socket.close()
            except (socket.error, OSError):
                pass
            self.client_socket = None

    def disconnect(self):
        if not self.is_connected:
            return
        self.is_connected = False
        try:
            if self.client_socket:
                self.client_socket.close()
        except (socket.error, OSError):
            pass
        self.client_socket = None

        self.connect_button.config(state=tk.NORMAL)
        self.disconnect_button.config(state=tk.DISABLED)
        self.submit_button.config(state=tk.DISABLED)

        self.log("DISCONNECTED.")


    # Function to keep listening to the server for messages
    def receive_loop(self):
        buffer = ""
        while self.is_connected:
            try:
                chunk = self.client_socket.recv(1024).decode()
                if not chunk:
                    self.log("SERVER CLOSED CONNECTION.")
                    self.disconnect()
                    break

                buffer += chunk

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        self.handle_server_message(line)

            except (socket.error, OSError):
                self.disconnect() # In case error happens while reading
                break

    # Function to handle different types of messages coming from the server
    # We use a custom formatting since we can only send raw messages
    # Has custom types like ERROR, QUESSTION, SCORE etc. so client program knows what to do
    def handle_server_message(self, msg: str):
        # Protocol: TYPE|payload...
        parts = msg.split("|")
        mtype = parts[0].strip()

        if mtype == "ERROR":
            # Display the error in log and messagebox
            text = parts[1] if len(parts) > 1 else "Unknown server error."
            self.log("! Server Error !: " + text)
            messagebox.showerror("Server Error", text)
            self.disconnect()

        elif mtype == "MSG":
            # Display generic message in log
            text = parts[1] if len(parts) > 1 else ""
            self.log(text)

        elif mtype == "QUESTION":
            # Display incoming question
            # QUESTION|q|choiceA|choiceB|choiceC|idx|total
            if len(parts) >= 7:
                q = parts[1]
                ca = parts[2]
                cb = parts[3]
                cc = parts[4]
                idx = parts[5]
                total = parts[6]

                # Format the question in a readable way to print to screen
                question = ""
                question += f"QUESTION {idx}/{total}\n"
                question += q + "\n\n"
                question += "A) " + ca + "\n"
                question += "B) " + cb + "\n"
                question += "C) " + cc + "\n"
                question += "\nSelect A/B/C and press Submit."

                self.set_question_display(question)
                self.log(f"--- Question {idx} received. Submit your answer. ---")

                # Enable submit button
                self.submit_button.config(state=tk.NORMAL)
            else:
                self.log("--- Malformed QUESTION message received. ---")

        elif mtype == "YOURRESULT":
            # Display personal result in log
            text = parts[1] if len(parts) > 1 else ""
            self.log(text)

            # Disable submit button after a result, to avoid sending multiple answers before receiving a new question
            self.submit_button.config(state=tk.DISABLED)

        elif mtype == "SCORE":
            # Display scoreboard in log
            text = "|".join(parts[1:]) if len(parts) > 1 else ""
            text = text.replace("\\n", "\n")
            self.log("--- Scoreboard Update ---")
            for line in text.split("\n"):
                self.log(line)
            self.log("--- End Scoreboard ---")

        elif mtype == "GAMEOVER":
            # Display final scoreboard in log
            text = "|".join(parts[1:]) if len(parts) > 1 else ""
            text = text.replace("\\n", "\n")
            self.log("########################################")
            self.log("##########    G A M E   O V E R   ##########")
            for line in text.split("\n"):
                self.log(line)
            self.log("########################################")
            self.submit_button.config(state=tk.DISABLED)
            self.log("\nDisconnecting from the server...")
            self.set_question_display("")
            self.disconnect()

        else:
            # If server sends something that is not defined
            self.log("UNKNOWN SERVER MESSAGE: " + msg)

    # Function to send answers to server
    def submit_answer(self):
        if not self.is_connected:
            self.log("Not connected; cannot submit.")
            return

        ans = self.answer_var.get().strip().upper()
        if ans not in ["A", "B", "C"]:
            self.log("Invalid radio choice.") # (Shouldn't happen, just to be sure)
            return

        try:
            # Send the answer to the server
            self.client_socket.sendall(("ANSWER|" + ans).encode())
            self.log("ANSWER SENT: " + ans)

            # Disable the button immediately after submission
            self.submit_button.config(state=tk.DISABLED)
        except (socket.error, OSError):
            self.log("Failed to send answer (socket error).")
            self.disconnect()

    # Closing
    def on_closing(self):
        try:
            self.disconnect()
        except Exception:
            pass
        try:
            self.master.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    root = tk.Tk()
    app = QuizClient(root)
    root.mainloop()