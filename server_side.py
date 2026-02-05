# SERVER

import tkinter as tk
from tkinter import messagebox
import socket
import threading
import random

class QuizServer:
    def __init__(self, master: tk.Tk):
        self.master = master
        master.title("Quiz - Server")
        master.grid_columnconfigure(index=list(range(4)), weight=1)
        master.grid_rowconfigure(index=list(range(3)), weight=1)

        self.server_socket = None
        self.is_listening = False
        self.accept_thread = None # Thread that will handle incoming connections

        # Dictionary of name-socket pairs (used in sending messages)
        self.clients_by_name = {}

        self.game_active = False
        self.disconnected_names_this_game = set() # This is needed so the players that left
                                                  # still show up at the end scoreboard

        self.questions = []
        self.game_question_pool = [] # Holds the shuffled questions for randomization
        self.num_questions_to_ask = 0 # Will be updated by the entry field later
        self.question_index = 0

        self.scores = {}  # Dictionary of name-score pairs

        # Lock is used to avoid race conditions when clients answer at the same time
        self.answer_lock = threading.Lock()
        self.waiting_for_answers = False
        self.current_correct = None
        self.current_answers = {}  # Dictionary of name-answer pairs
        self.first_correct = None

        self.game_thread = None

        self.create_widgets()

    def create_widgets(self):
        # Frame that contains input fields (Port, Question file, Number of questions) & their buttons
        inputs_frame = tk.Frame(self.master)
        inputs_frame.grid(row=0, column=0, columnspan=4, padx=10, pady=10, sticky="NWSE")
        inputs_frame.grid_columnconfigure(index=list(range(8)), weight=1)

        # Port entry field
        tk.Label(inputs_frame, text="Port:").grid(row=0, column=0, sticky="E")
        self.port_entry = tk.Entry(inputs_frame)
        self.port_entry.grid(row=0, column=1, sticky="WE")

        # Button that starts listening the input port
        self.listen_button = tk.Button(inputs_frame, text="Listen", command=self.toggle_listening)
        self.listen_button.grid(row=0, column=2, padx=5, sticky="WE")

        # Name of the file that contains the questions
        tk.Label(inputs_frame, text="Questions file:").grid(row=0, column=3, sticky="E")
        self.file_entry = tk.Entry(inputs_frame)
        self.file_entry.grid(row=0, column=4, sticky="WE")

        # Button that loads questions from the input file
        self.load_button = tk.Button(inputs_frame, text="Load File", command=self.load_file)
        self.load_button.grid(row=0, column=5, padx=5, sticky="WE")

        # Number of questions entry field
        tk.Label(inputs_frame, text="Number of questions to ask:").grid(row=0, column=6, sticky="E")
        self.num_of_questions_entry = tk.Entry(inputs_frame)
        self.num_of_questions_entry.grid(row=0, column=7, sticky="WE")

        # Frame that contains start game and kick all buttons
        game_buttons_frame = tk.Frame(self.master)
        game_buttons_frame.grid(row=1, column=0, columnspan=4, padx=10, pady=5, sticky="NWSE")
        game_buttons_frame.grid_columnconfigure(index=list(range(4)), weight=1)

        # Start game button
        self.start_game_button = tk.Button(game_buttons_frame, text="Start Game", command=self.start_game)
        self.start_game_button.grid(row=0, column=0, columnspan=2, padx=5, sticky="WE")

        # Kick all button
        self.kick_all_button = tk.Button(game_buttons_frame, text="Kick All (End Game)", command=self.force_end_game)
        self.kick_all_button.grid(row=0, column=2, columnspan=2, padx=5, sticky="WE")

        # Frame that contains the server log
        log_frame = tk.Frame(self.master)
        log_frame.grid(row=2, column=0, columnspan=4, padx=10, pady=10, sticky="NWSE")
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)

        self.log_list = tk.Listbox(log_frame, height=20)
        self.log_list.grid(row=0, column=0, sticky="NWSE")

        sb = tk.Scrollbar(log_frame, orient="vertical")
        sb.grid(row=0, column=1, sticky="NS")
        self.log_list.config(yscrollcommand=sb.set)
        sb.config(command=self.log_list.yview)

        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)


    # Helper function that logs the message into the activity log
    def log(self, msg: str):
        self.log_list.insert(tk.END, msg)
        self.log_list.yview(tk.END)

    # Toggles listening on the input port
    def toggle_listening(self):
        if self.is_listening:
            self.stop_listening()
        else:
            self.start_listening()

    def start_listening(self):
        port_str = self.port_entry.get().strip() # Read the port from the entry field
        if not port_str:
            messagebox.showerror("Error", "Please enter a port number.")
            return

        try:
            # Create the socket and bind it to the port
            port = int(port_str)
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.bind(("", port))
            self.server_socket.listen()

            self.is_listening = True
            self.listen_button.config(text="Stop Listening") # Change the button's text
            self.log("<SERVER>: Listening on port " + str(port) + ". Waiting for clients...")

            self.accept_thread = threading.Thread(target=self.accept_connections, daemon=True)
            self.accept_thread.start()

        except (socket.error, ValueError) as e:
            messagebox.showerror("Server Error", "Could not start server: " + str(e))
            self.is_listening = False
            try:
                if self.server_socket:
                    self.server_socket.close()
            except (socket.error, OSError):
                pass
            self.server_socket = None

    def stop_listening(self):
        self.log("<SERVER>: Stopping listening. Disconnecting all clients.")
        self.is_listening = False

        # Ends active game & kicks all players since server will stop listening
        self.force_end_game()

        # In case the game wasn't active, we still need to kick all the players
        for name in list(self.clients_by_name.keys()):
            self.remove_client_by_name(name, reason="Server stopped listening")

        try:
            if self.server_socket:
                self.server_socket.close()
        except (socket.error, OSError):
            pass

        self.server_socket = None
        self.listen_button.config(text="Listen")
        self.log("<SERVER>: Stopped.")

    # The function that the thread that accepts connections will run
    def accept_connections(self):
        while self.is_listening:
            try:
                client_socket, client_addr = self.server_socket.accept()

                # Client sends name immediately, otherwise closes the connection
                name = client_socket.recv(1024).decode().strip()
                if not name:
                    try:
                        client_socket.close()
                    except (socket.error, OSError):
                        pass
                    continue

                # Reject if game is active
                if self.game_active:
                    self.log("CONNECT REJECT: " + name + " from " + str(client_addr) + " (game already active).")
                    self.send_raw(client_socket, "ERROR|Game already started. Try later.") # Keep ERROR| for client logic
                    try:
                        client_socket.close()
                    except (socket.error, OSError):
                        pass
                    continue

                # Reject duplicate names
                if name in self.clients_by_name:
                    self.log("CONNECT REJECT: name " + name + " already connected. From " + str(client_addr) + ".")
                    self.send_raw(client_socket, "ERROR|Name already in use. Choose another.") # Keep ERROR| for client logic
                    try:
                        client_socket.close()
                    except (socket.error, OSError):
                        pass
                    continue

                # Accept
                self.clients_by_name[name] = client_socket
                self.scores[name] = 0
                self.log("CONNECT OK: " + str(client_addr[0]) + ":" + str(client_addr[1]) + " as " + name)
                self.broadcast("MSG|" + name + " connected to server.")

                # A new thread is created to handle every client seperetaly
                t = threading.Thread(target=self.handle_client, args=(client_socket, name), daemon=True)
                t.start()

            except (socket.error, OSError):
                break

    # The function that client handling threads run on
    def handle_client(self, client_socket, name: str):
        while self.is_listening:
            try:
                data = client_socket.recv(1024).decode()
                if not data:
                    self.remove_client_by_name(name, reason="Client closed connection (recv empty).")
                    break

                data = data.strip()
                if not data:
                    continue

                # This is the special formatting used when clients answer a question
                if data.startswith("ANSWER|"):
                    parts = data.split("|")
                    if len(parts) >= 2:
                        ans = parts[1].strip().upper()
                        if ans not in ["A", "B", "C"]:
                            self.send_to_name(name, "MSG|Invalid answer. Use A, B, or C.")
                            self.log("ANSWER INVALID: '" + name + "' sent '" + ans + "'")
                        else:
                            self.process_answer(name, ans)
                    else:
                        self.send_to_name(name, "MSG|Invalid answer format.")
                else:
                    self.log("RECV (ignored) from '" + name + "': " + str(data))

            except (socket.error, OSError):
                self.remove_client_by_name(name, reason="Socket error / reset.")
                break

    # Function used in removing a certain client from the server
    def remove_client_by_name(self, name: str, reason: str):
        if name not in self.clients_by_name:
            return

        s = self.clients_by_name[name]
        self.log("DISCONNECT: '" + name + "' disconnected. Reason: " + reason)

        try:
            s.close()
        except (socket.error, OSError):
            pass

        # Explicit removal using 'del' instead of .pop() to match seen.py usage pattern
        if name in self.clients_by_name:
            del self.clients_by_name[name]

        self.broadcast("MSG|'" + name + "' disconnected.")

        if self.game_active:
            self.disconnected_names_this_game.add(name)


    # File loading function
    def load_file(self):
        filename = self.file_entry.get().strip()
        if not filename:
            messagebox.showerror("Error", "Enter a question file name.")
            return

        try:
            questions = []
            one_question = {}
            lines = []

            with open(filename, "r", encoding="utf-8") as f:
                lines = f.readlines()

            counter = 0
            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # This part basically organizes lines in the format they are given in
                if counter % 5 == 0: # Question
                    one_question["Question"] = line

                elif counter % 5 == 1 or counter % 5 == 2 or counter % 5 == 3: # Choices
                    if "Choices" in one_question:
                        one_question["Choices"].append(line)
                    else:
                        one_question["Choices"] = [line]

                elif counter % 5 == 4: # Answer
                    parts = line.split()
                    one_question["Answer"] = parts[-1].strip().upper()

                    questions.append(one_question.copy())
                    one_question.clear()

                counter += 1

            # Handle potential incomplete question at the end
            if len(one_question) > 0:
                self.log("FILE WARNING: Last question was incomplete and ignored.")

            # No questions read correctly
            if len(questions) == 0:
                messagebox.showerror("Error", "File read OK but no complete questions were parsed.")
                self.questions = []
                return

            self.questions = questions
            self.log("FILE OK: Loaded " + str(len(self.questions)) + " complete questions from '" + filename + "'.")

        except Exception as e:
            messagebox.showerror("File Error", "Could not open/read file: " + str(e))
            self.questions = []
            self.log("FILE ERROR: Could not open/read '" + filename + "'. Exception: " + str(e))

    # Starts the game
    def start_game(self):
        if not self.is_listening:
            messagebox.showerror("Error", "Server is not listening yet.")
            return
        if self.game_active:
            messagebox.showerror("Error", "Game already active.")
            return
        if len(self.clients_by_name) < 2:
            messagebox.showerror("Error", "Need at least 2 connected clients to start.")
            return
        if not self.questions:
            messagebox.showerror("Error", "Load the question file successfully first.")
            return

        num_of_questions_str = self.num_of_questions_entry.get().strip()
        if not num_of_questions_str:
            messagebox.showerror("Error", "Enter number of questions to ask.")
            return
        try:
            n = int(num_of_questions_str)
            if n <= 0:
                raise ValueError("Number must be > 0.")
        except Exception as e:
            messagebox.showerror("Error", f"Invalid number of questions: {e}")
            return

        self.num_questions_to_ask = n
        self.question_index = 0
        self.game_active = True
        self.waiting_for_answers = False
        self.disconnected_names_this_game = set()

        # Prepare randomized pool for this specific round
        self.game_question_pool = self.questions.copy()
        random.shuffle(self.game_question_pool)

        self.scores = {} # To delete previous games' scores from the memory
        for name in list(self.clients_by_name.keys()):
            self.scores[name] = 0

        self.log("GAME: Starting new game.")
        self.log(f"GAME: Players ({len(self.clients_by_name)}): {', '.join(self.clients_by_name.keys())}")
        self.log("GAME: Questions to ask: " + str(self.num_questions_to_ask) + " (loops file if needed).")

        sb = self.format_scoreboard(final=False)
        self.broadcast("MSG|GAME STARTED. Initial scoreboard sent.")
        # Replace \n with \\n for sending to clients
        self.broadcast("SCORE|" + sb.replace("\n", "\\n"))

        # The thread that will handle the game loop
        self.game_thread = threading.Thread(target=self.game_loop, daemon=True)
        self.game_thread.start()

    # Function that ends the game and kicks all players if game is active
    def force_end_game(self):
        if not self.game_active:
            return

        self.log("GAME: Force-ending game now.")
        self.game_active = False
        self.waiting_for_answers = False

        final_sb = self.format_scoreboard(final=True)
        # Replace \n with \\n for sending sending to clients
        self.broadcast("GAMEOVER|" + final_sb.replace("\n", "\\n"))

        # Clients handle disconnection after "GAMEOVER|", so we can close the sockets here
        for name in list(self.clients_by_name.keys()):
            self.remove_client_by_name(name, reason="Game ended by server command.")

    # The game logic
    def game_loop(self):
        while self.game_active and self.question_index < self.num_questions_to_ask:
            # If fewer than 2 players at the start of a question, end immediately.
            if len(self.clients_by_name) < 2:
                self.log("GAME: Ending because fewer than 2 players remain connected.")
                break

            q = self.game_question_pool[self.question_index % len(self.game_question_pool)] # Pick the question from the randomized pool

            q_text = q.get("Question", "Missing Question Text")
            choices = q.get("Choices", ["A: N/A", "B: N/A", "C: N/A"])
            ans = q.get("Answer", "A").strip().upper()

            if ans not in ["A", "B", "C"]: # To make sure the question file only has a,b or c as answers
                self.log("GAME WARNING: invalid correct answer '" + str(ans) + "'. Treating as 'A'.")
                ans = "A"

            # Setup answering state
            self.answer_lock.acquire()
            self.waiting_for_answers = True
            self.current_correct = ans
            self.current_answers = {}
            self.first_correct = None
            self.answer_lock.release()

            # Broadcast question to all clients
            # (this is the determined format for sending the question, client.py works in the same format)
            msg = "QUESTION|" + q_text + "|" + choices[0] + "|" + choices[1] + "|" + choices[2] + "|" + str(self.question_index + 1) + "|" + str(self.num_questions_to_ask)
            self.broadcast(msg)

            self.log("------------------------------------------------------------")
            self.log("QUESTION "+str(self.question_index + 1)+"/"+str(self.num_questions_to_ask)+": "+str(q_text))
            self.log("GAME: Waiting for ALL connected players to submit an answer...")

            # Wait until the number of received answers matches current connected players.
            while self.game_active:
                self.answer_lock.acquire()
                ans_count = len(self.current_answers)
                player_count = len(self.clients_by_name)
                self.answer_lock.release()

                if ans_count >= player_count:
                    break

            if not self.game_active:
                break

            self.score_current_question()

            self.question_index += 1

            # After scoring if less than 2 players remain -> end game
            if len(self.clients_by_name) < 2:
                self.log("GAME: Ending after scoring because fewer than 2 players remain connected.")
                break

        self.end_game_naturally()

    # Processes the received answer, uses locks to avoid race conditions
    def process_answer(self, name: str, ans: str):
        if not self.game_active:
            self.send_to_name(name, "MSG|No active game right now.")
            self.log("ANSWER IGNORED: '" + name + "' answered but no active game.")
            return

        self.answer_lock.acquire()

        if not self.waiting_for_answers:
            self.answer_lock.release()
            self.send_to_name(name, "MSG|Not accepting answers at the moment.")
            self.log("ANSWER IGNORED: '" + name + "' answered outside answering phase.")
            return

        if name in self.current_answers:
            self.answer_lock.release()
            self.send_to_name(name, "MSG|You already submitted an answer for this question.")
            self.log("ANSWER DUPLICATE: '" + name + "' tried second answer '" + ans + "'.")
            return

        self.current_answers[name] = ans

        if ans == self.current_correct and self.first_correct is None:
            self.first_correct = name

        self.log("ANSWER RECV: '"+name+"' -> "+ans+" (answers "+str(len(self.current_answers))+"/"+str(len(self.clients_by_name))+")")

        self.answer_lock.release()

    # Function to calculate the scoring for the current question
    def score_current_question(self):
        # Lock acquired here to protect score update
        self.answer_lock.acquire()

        correct = self.current_correct
        first = self.first_correct
        num_players = len(self.clients_by_name)
        bonus = max(0, num_players - 1)

        self.log(f"SCORING: Correct='{correct}'. First correct={first if first else 'None'} (bonus={bonus}).")

        for name in list(self.clients_by_name.keys()):
            client_answer = self.current_answers.get(name, None)

            # Shouldn't be possible since server waits for everyone to answer, just in case
            if client_answer is None:
                personal_result = "You did not submit an answer. Correct was '" + str(correct) + "'. +0 points."
                self.send_to_name(name, "YOURRESULT|" + personal_result)
                self.log("SCORING: '" + name + "' no answer. +0.")
                continue

            # Answered correctly
            if client_answer == correct:
                points = 1
                extra = bonus if (first == name) else 0

                # Check if name is in scores, if not, initialize to 0 before adding
                if name not in self.scores:
                    self.scores[name] = 0

                self.scores[name] = self.scores[name] + points + extra

                if extra > 0:
                    personal_result = "Correct AND first! '"+str(client_answer)+"' is right. +"+str(points)+"+"+str(extra)+"="+str(points+extra)+" points."
                else:
                    personal_result = "Correct. '"+str(client_answer)+"' is right. +"+str(points)+" point."
                self.send_to_name(name, "YOURRESULT|" + personal_result)
                self.log("SCORING: '"+name+"' correct. +"+str(points)+"+"+str(extra)+". Total="+str(self.scores[name]))

            else:
                personal_result = f"Wrong. You answered '{client_answer}'. Correct was '{correct}'. +0 points."
                self.send_to_name(name, "YOURRESULT|" + personal_result)
                self.log(f"SCORING: '{name}' wrong ('{client_answer}'). +0. Total={self.scores.get(name,0)}")

        sb = self.format_scoreboard(final=False)
        # Replace \n with \\n for sending to clients
        sb_for_send = sb.replace("\n", "\\n")
        self.broadcast("SCORE|" + sb_for_send)
        self.log("SCOREBOARD SENT:\n" + sb)

        self.waiting_for_answers = False

        self.answer_lock.release()

    # If the game ends naturally, this function runs
    def end_game_naturally(self):
        if not self.game_active:
            return

        self.game_active = False
        self.waiting_for_answers = False

        final_sb = self.format_scoreboard(final=True)

        self.log("GAME: Ended. Final scoreboard/rankings calculated.")
        self.log("FINAL SCOREBOARD:\n" + final_sb)

        # Replace \n with \\n for sending to clients
        final_sb_for_send = final_sb.replace("\n", "\\n")
        self.broadcast("GAMEOVER|" + final_sb_for_send)

    # Helper functions to send data to cleints
    def send_raw(self, sock, msg: str):
        try:
            sock.sendall((msg + "\n").encode())
        except (socket.error, OSError):
            pass

    # Send to a spesific name
    def send_to_name(self, name: str, msg: str):
        if name not in self.clients_by_name:
            return
        self.send_raw(self.clients_by_name[name], msg)

    # Send to all connected clients
    def broadcast(self, msg: str):
        for name in list(self.clients_by_name.keys()):
            self.send_to_name(name, msg)

    # Scoreboard formatting
    def format_scoreboard(self, final: bool):
        items = list(self.scores.items())
        # Sort by score (descending) then by name (ascending)
        items.sort(key=lambda x: (-x[1], x[0]))

        lines = []
        lines.append("FINAL SCOREBOARD (with rankings):" if final else "SCOREBOARD:")

        prev_score = None
        rank = 0
        tie_count = 0

        for (name, score) in items:
            if prev_score is None:
                rank = 1
                tie_count = 1
            else:
                if score == prev_score:
                    tie_count += 1
                else:
                    rank = rank + tie_count
                    tie_count = 1
            prev_score = score
            lines.append(f"#{rank}) {name}: {score} points")

        if final and items:
            top_score = items[0][1]
            winners = [n for (n, sc) in items if sc == top_score]
            if len(winners) == 1:
                lines.append(f"\nWINNER: {winners[0]} with {top_score} points!")
            else:
                lines.append(f"\nWINNERS (tie): {', '.join(winners)} with {top_score} points!")

        # Also include disconnected names, but only if they were part of this game.
        if self.disconnected_names_this_game:
            lines.append(f"\nDisconnected Players: {', '.join(sorted(list(self.disconnected_names_this_game)))}")

        return "\n".join(lines)

    def on_closing(self):
        try:
            if self.is_listening:
                self.stop_listening()
        except Exception:
            pass
        try:
            self.master.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    root = tk.Tk()
    app = QuizServer(root)
    root.mainloop()