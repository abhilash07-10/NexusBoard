import os
import random
import string
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")
app.secret_key = os.environ.get('FLASK_SECRET', 'change_this_secret')

# DB config — change if needed
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_NAME = os.environ.get('DB_NAME', 'nexusboard')
DB_USER = os.environ.get('DB_USER', 'postgres')
DB_PASS = os.environ.get('DB_PASS', 'Abhi2002')
DB_PORT = os.environ.get('DB_PORT', '5432')

def get_db_conn():
    return psycopg2.connect(
        host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT
    )

def gen_code():
    return 'NXB' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

def log_action(board_id, user_id, action):
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO history (board_id, user_id, action) VALUES (%s, %s, %s)",
                    (board_id, user_id, action))
        conn.commit()
        socketio.emit('history_update', {'board_id': board_id}, room=f'board_{board_id}')

    except Exception:
        conn.rollback()
    finally:
        cur.close()
        conn.close()

# ---------- AUTH ----------
@app.route('/')
def index():
    if session.get('user'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        email = request.form.get('email','').strip().lower()
        password = request.form.get('password','')
        if not username or not email or not password:
            flash('All fields required', 'error')
            return render_template('auth.html', mode='register')
        hashed = generate_password_hash(password)
        conn = get_db_conn()
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
                        (username, email, hashed))
            conn.commit()
            flash('Registration successful. Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            conn.rollback()
            flash('Registration error: ' + str(e), 'error')
        finally:
            cur.close(); conn.close()
    return render_template('auth.html', mode='register')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower()
        password = request.form.get('password','')
        conn = get_db_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT id, username, email, password_hash FROM users WHERE email=%s", (email,))
            user = cur.fetchone()
            if user and check_password_hash(user['password_hash'], password):
                session['user'] = {'id': user['id'], 'username': user['username']}
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid credentials', 'error')
        except Exception as e:
            flash('Login error: ' + str(e), 'error')
        finally:
            cur.close(); conn.close()
    return render_template('auth.html', mode='login')


@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out', 'success')
    return redirect(url_for('login'))

# ---------- DASHBOARD ----------
@app.route('/dashboard')
def dashboard():
    if not session.get('user'):
        return redirect(url_for('login'))
    user_id = session['user']['id']
    conn = get_db_conn(); cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Boards user owns
        cur.execute("SELECT * FROM boards WHERE owner_id=%s ORDER BY created_at DESC", (user_id,))
        owned = cur.fetchall()
        # Boards user joined (exclude ones they own to avoid duplication)
        cur.execute("""
            SELECT b.*, u.username AS owner_name
            FROM boards b
            JOIN users u ON b.owner_id = u.id
            JOIN user_boards ub ON ub.board_id = b.id
            WHERE ub.user_id = %s AND b.owner_id != %s
            ORDER BY b.created_at DESC
        """, (user_id, user_id))
        joined = cur.fetchall()
    finally:
        cur.close(); conn.close()
    return render_template('dashboard.html', user=session['user'], owned_boards=owned, joined_boards=joined)

# ---------- CREATE BOARD ----------
@app.route('/add_board', methods=['POST'])
def add_board():
    if not session.get('user'):
        return redirect(url_for('login'))
    name = request.form.get('name','').strip()
    description = request.form.get('description','').strip()
    if not name:
        flash('Board name required', 'error'); return redirect(url_for('dashboard'))
    owner_id = session['user']['id']
    code = gen_code()
    conn = get_db_conn(); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO boards (name, description, board_code, owner_id) VALUES (%s,%s,%s,%s)",
                    (name, description, code, owner_id))
        conn.commit()
        # auto add owner as member too (optional, but helpful)
        cur.execute("INSERT INTO user_boards (user_id, board_id) VALUES (%s, currval('boards_id_seq'))", (owner_id,))
        conn.commit()
        flash(f'Board created. Code: {code}', 'success')
        socketio.emit('board_update')
    except Exception as e:
        conn.rollback(); flash('Create board error: ' + str(e), 'error')
    finally:
        cur.close(); conn.close()
    return redirect(url_for('dashboard'))

# ---------- JOIN BOARD ----------
@app.route('/join_board', methods=['POST'])
def join_board():
    if not session.get('user'):
        return redirect(url_for('login'))
    code = request.form.get('board_code','').strip()
    if not code:
        flash('Board code required', 'error'); return redirect(url_for('dashboard'))
    user_id = session['user']['id']
    conn = get_db_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM boards WHERE board_code=%s", (code,))
        row = cur.fetchone()
        if not row:
            flash('Invalid board code', 'error')
        else:
            board_id = row[0]
            # check existing
            cur.execute("SELECT id FROM user_boards WHERE user_id=%s AND board_id=%s", (user_id, board_id))
            if cur.fetchone():
                flash('Already joined', 'info')
            else:
                cur.execute("INSERT INTO user_boards (user_id, board_id) VALUES (%s,%s)", (user_id, board_id))
                conn.commit()
                flash('Joined board', 'success')
    except Exception as e:
        conn.rollback(); flash('Join error: ' + str(e), 'error')
    finally:
        cur.close(); conn.close()
    return redirect(url_for('dashboard'))

# ---------- OPEN BOARD VIEW ----------
@app.route('/board/<int:board_id>')
def board_view(board_id):
    if not session.get('user'):
        return redirect(url_for('login'))
    user_id = session['user']['id']
    search = request.args.get('search', '').strip().lower()
    filter_user = request.args.get('filter', '')

    conn = get_db_conn(); cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT b.*, u.username AS owner_name FROM boards b JOIN users u ON b.owner_id=u.id WHERE b.id=%s", (board_id,))
        board = cur.fetchone()
        if not board:
            flash('Board not found', 'error'); return redirect(url_for('dashboard'))

        cur.execute("SELECT 1 FROM user_boards WHERE board_id=%s AND user_id=%s", (board_id, user_id))
        if not cur.fetchone():
            flash('You are not a member of this board', 'error'); return redirect(url_for('dashboard'))

        # members
        cur.execute("""
            SELECT u.id, u.username
            FROM users u
            JOIN user_boards ub ON ub.user_id = u.id
            WHERE ub.board_id = %s
            ORDER BY u.username
        """, (board_id,))
        members = cur.fetchall()

        # tasks with optional search/filter
        query = """
            SELECT t.*, u.username AS assigned_name
            FROM tasks t
            LEFT JOIN users u ON t.assigned_to = u.id
            WHERE t.board_id=%s
        """
        params = [board_id]

        if search:
            query += " AND LOWER(t.name) LIKE %s"
            params.append(f"%{search}%")
        if filter_user:
            query += " AND t.assigned_to=%s"
            params.append(filter_user)

        query += " ORDER BY t.position ASC"
        cur.execute(query, tuple(params))
        tasks = cur.fetchall()
    finally:
        cur.close(); conn.close()

    return render_template('board.html', board=board, members=members, tasks=tasks,
                           user=session['user'], search=search, filter_user=filter_user)


# ---------- ADD TASK ----------
@app.route('/add_task/<int:board_id>', methods=['POST'])
def add_task(board_id):
    if not session.get('user'):
        return redirect(url_for('login'))
    name = request.form.get('name','').strip()
    description = request.form.get('description','').strip()
    assigned_to = request.form.get('assigned_to') or None
    comments = request.form.get('comments','').strip()
    due_date = request.form.get('due_date') or None
    if not name:
        flash('Task name required', 'error'); return redirect(url_for('board_view', board_id=board_id))
    # parse due_date if provided (expected ISO YYYY-MM-DD or datetime)
    dt_due = None
    if due_date:
        try:
            dt_due = datetime.fromisoformat(due_date)
        except Exception:
            flash('Invalid due date format. Use YYYY-MM-DD or ISO format.', 'error'); return redirect(url_for('board_view', board_id=board_id))
    conn = get_db_conn(); cur = conn.cursor()
    try:
        progress_percent = int(request.form.get('progress_percent', 0))
        cur.execute(
            "INSERT INTO tasks (name, description, board_id, assigned_to, comments, due_date, progress_percent) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (name, description, board_id, assigned_to, comments, dt_due, progress_percent)
        )
        log_action(board_id, session['user']['id'], f"Created task '{name}'")
        conn.commit(); flash('Task added', 'success')
        socketio.emit('task_update', {'board_id': board_id}, room=f'board_{board_id}')
    except Exception as e:
        conn.rollback(); flash('Add task error: ' + str(e), 'error')
    finally:
        cur.close(); conn.close()
    return redirect(url_for('board_view', board_id=board_id))

# ---------- EDIT TASK ----------
@app.route('/edit_task/<int:task_id>', methods=['GET', 'POST'])
def edit_task(task_id):
    if not session.get('user'):
        return redirect(url_for('login'))
    conn = get_db_conn(); cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        if request.method == 'POST':
            name = request.form.get('name').strip()
            description = request.form.get('description','').strip()
            assigned_to = request.form.get('assigned_to') or None
            comments = request.form.get('comments','').strip()
            due_date = request.form.get('due_date') or None
            progress_percent = int(request.form.get('progress_percent', 0))
            dt_due = None
            if due_date:
                try:
                    dt_due = datetime.fromisoformat(due_date)
                except:
                    flash('Invalid due date', 'error')
                    return redirect(request.referrer)
            cur.execute("SELECT board_id FROM tasks WHERE id=%s", (task_id,))
            task_row = cur.fetchone()
            if not task_row:
                flash('Task not found', 'error'); return redirect(url_for('dashboard'))
            board_id = task_row['board_id']
            # check membership
            user_id = session['user']['id']
            cur.execute("SELECT 1 FROM user_boards WHERE user_id=%s AND board_id=%s", (user_id, board_id))
            if not cur.fetchone():
                flash('Not authorized', 'error'); return redirect(url_for('dashboard'))
            cur.execute("""
                UPDATE tasks
                SET name=%s, description=%s, assigned_to=%s, comments=%s, due_date=%s, progress_percent=%s
                WHERE id=%s
            """, (name, description, assigned_to, comments, dt_due, progress_percent, task_id))
            conn.commit()
            log_action(board_id, session['user']['id'], f"Edited task '{name}'")
            flash('Task updated', 'success')
            socketio.emit('task_update', {'board_id': board_id}, room=f'board_{board_id}')
            return redirect(url_for('board_view', board_id=board_id))
        # GET: show form
        cur.execute("SELECT * FROM tasks WHERE id=%s", (task_id,))
        task = cur.fetchone()
        if not task:
            flash('Task not found', 'error'); return redirect(url_for('dashboard'))
        board_id = task['board_id']
        # load members for select
        cur.execute("""
            SELECT u.id, u.username
            FROM users u
            JOIN user_boards ub ON ub.user_id = u.id
            WHERE ub.board_id = %s
            ORDER BY u.username
        """, (board_id,))
        members = cur.fetchall()
    finally:
        cur.close(); conn.close()
    return render_template('edit_task.html', task=task, members=members)

# ---------- DELETE TASK ----------
@app.route('/delete_task/<int:task_id>')
def delete_task(task_id):
    if not session.get('user'):
        return redirect(url_for('login'))
    conn = get_db_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT board_id FROM tasks WHERE id=%s", (task_id,))
        row = cur.fetchone()
        if not row:
            flash('Task not found', 'error'); return redirect(url_for('dashboard'))
        board_id = row[0]
        # verify membership
        user_id = session['user']['id']
        cur.execute("SELECT 1 FROM user_boards WHERE user_id=%s AND board_id=%s", (user_id, board_id))
        if not cur.fetchone():
            flash('Not authorized', 'error'); return redirect(url_for('dashboard'))
        cur.execute("DELETE FROM tasks WHERE id=%s", (task_id,))
        log_action(board_id, session['user']['id'], f"Deleted a task (ID {task_id})")
        conn.commit(); flash('Task deleted', 'success')
        socketio.emit('task_update', {'board_id': board_id}, room=f'board_{board_id}')
    except Exception as e:
        conn.rollback(); flash('Delete task error: '+str(e), 'error')
    finally:
        cur.close(); conn.close()
    return redirect(url_for('board_view', board_id=board_id))

# ---------- PERFORMANCE ----------
@app.route('/performance/<int:board_id>')
def performance(board_id):
    if not session.get('user'):
        return redirect(url_for('login'))
    conn = get_db_conn(); cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT u.username, COALESCE(AVG(t.progress_percent),0) AS avg_progress
            FROM users u
            JOIN user_boards ub ON ub.user_id = u.id
            LEFT JOIN tasks t ON t.assigned_to = u.id AND t.board_id = %s
            WHERE ub.board_id = %s
            GROUP BY u.username
            ORDER BY avg_progress DESC
        """, (board_id, board_id))
        data = cur.fetchall()
    finally:
        cur.close(); conn.close()
    return render_template('performance.html', data=data)

# ---------- PROJECT STATUS ----------
@app.route('/status/<int:board_id>')
def project_status(board_id):
    if not session.get('user'):
        return redirect(url_for('login'))
    conn = get_db_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT COALESCE(AVG(progress_percent),0) FROM tasks WHERE board_id=%s", (board_id,))
        percent = cur.fetchone()[0]
    finally:
        cur.close(); conn.close()
    return render_template('status.html', percent=percent)

@app.route('/update_task_order/<int:board_id>', methods=['POST'])
def update_task_order(board_id):
    if not session.get('user'):
        return "Unauthorized", 403
    data = request.get_json()
    ordered_ids = data.get('ordered_ids', [])
    if not ordered_ids:
        return "No order provided", 400
    conn = get_db_conn(); cur = conn.cursor()
    try:
        for position, task_id in enumerate(ordered_ids):
            cur.execute("UPDATE tasks SET position=%s WHERE id=%s AND board_id=%s", (position, task_id, board_id))
        conn.commit()
        socketio.emit('task_update', {'board_id': board_id}, room=f'board_{board_id}')
        return "Order updated", 200
    except Exception as e:
        conn.rollback()
        return str(e), 500
    finally:
        cur.close(); conn.close()

# ---------- EDIT BOARD ----------
@app.route('/edit_board/<int:board_id>', methods=['GET','POST'])
def edit_board(board_id):
    if not session.get('user'):
        return redirect(url_for('login'))
    conn = get_db_conn(); cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM boards WHERE id=%s", (board_id,))
        board = cur.fetchone()
        if not board:
            flash('Not found', 'error'); return redirect(url_for('dashboard'))
        if session['user']['id'] != board['owner_id']:
            flash('Only owner can edit board', 'error'); return redirect(url_for('dashboard'))
        if request.method == 'POST':
            name = request.form.get('name').strip()
            desc = request.form.get('description','').strip()
            cur.execute("UPDATE boards SET name=%s, description=%s WHERE id=%s", (name, desc, board_id))
            conn.commit(); flash('Board updated', 'success'); return redirect(url_for('dashboard'))
            socketio.emit('board_update')
    finally:
        cur.close(); conn.close()
    return render_template('edit_board.html', board=board)

# ---------- DELETE BOARD ----------
@app.route('/delete_board/<int:board_id>')
def delete_board(board_id):
    if not session.get('user'):
        return redirect(url_for('login'))
    conn = get_db_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT owner_id FROM boards WHERE id=%s", (board_id,))
        r = cur.fetchone()
        if not r:
            flash('Board not found', 'error'); return redirect(url_for('dashboard'))
        if r[0] != session['user']['id']:
            flash('Only owner can delete', 'error'); return redirect(url_for('dashboard'))
        cur.execute("DELETE FROM boards WHERE id=%s", (board_id,))
        conn.commit(); flash('Board deleted', 'success')
        socketio.emit('board_update')
    except Exception as e:
        conn.rollback(); flash('Delete board error: '+str(e), 'error')
    finally:
        cur.close(); conn.close()
    return redirect(url_for('dashboard'))

@app.route('/invite_member/<int:board_id>', methods=['POST'])
def invite_member(board_id):
    if not session.get('user'):
        return redirect(url_for('login'))
    conn = get_db_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT owner_id FROM boards WHERE id=%s", (board_id,))
        row = cur.fetchone()
        if not row:
            flash('Board not found.', 'error'); return redirect(url_for('dashboard'))
        if session['user']['id'] != row[0]:
            flash('Only owner can invite members.', 'error'); return redirect(url_for('board_view', board_id=board_id))
        email = request.form.get('email','').strip().lower()
        if not email:
            flash('Email required', 'error'); return redirect(url_for('board_view', board_id=board_id))
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        user = cur.fetchone()
        if not user:
            flash('User not found, ask them to register.', 'error'); return redirect(url_for('board_view', board_id=board_id))
        user_id = user[0]
        cur.execute("SELECT 1 FROM user_boards WHERE user_id=%s AND board_id=%s", (user_id, board_id))
        if cur.fetchone():
            flash('User already a member.', 'info'); return redirect(url_for('board_view', board_id=board_id))
        cur.execute("INSERT INTO user_boards (user_id, board_id) VALUES (%s,%s)", (user_id, board_id))
        conn.commit(); flash('Member invited successfully!', 'success')
        socketio.emit('member_update', {'board_id': board_id}, room=f'board_{board_id}')
    except Exception as e:
        conn.rollback(); flash('Invite error: '+str(e), 'error')
    finally:
        cur.close(); conn.close()
    return redirect(url_for('board_view', board_id=board_id))

@app.route('/remove_member/<int:board_id>/<int:user_id>')
def remove_member(board_id, user_id):
    if not session.get('user'):
        return redirect(url_for('login'))
    conn = get_db_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT owner_id FROM boards WHERE id=%s", (board_id,))
        row = cur.fetchone()
        if not row:
            flash('Board not found.', 'error'); return redirect(url_for('dashboard'))
        if session['user']['id'] != row[0]:
            flash('Only owner can remove members.', 'error'); return redirect(url_for('board_view', board_id=board_id))
        if user_id == row[0]:
            flash('Owner cannot remove themselves.', 'error'); return redirect(url_for('board_view', board_id=board_id))
        cur.execute("DELETE FROM user_boards WHERE user_id=%s AND board_id=%s", (user_id, board_id))
        conn.commit(); flash('Member removed successfully.', 'success')
        socketio.emit('member_update', {'board_id': board_id}, room=f'board_{board_id}')
    except Exception as e:
        conn.rollback(); flash('Remove member error: '+str(e), 'error')
    finally:
        cur.close(); conn.close()
    return redirect(url_for('board_view', board_id=board_id))

@app.route('/history/<int:board_id>')
def board_history(board_id):
    if not session.get('user'):
        return redirect(url_for('login'))
    conn = get_db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT h.*, u.username
            FROM history h
            LEFT JOIN users u ON h.user_id = u.id
            WHERE h.board_id = %s
            ORDER BY h.timestamp DESC
        """, (board_id,))
        logs = cur.fetchall()
    finally:
        cur.close()
        conn.close()
    return render_template('history.html', logs=logs)

@app.route('/delete_history/<int:log_id>', methods=['POST'])
def delete_history(log_id):
    if not session.get('user'):
        return "Unauthorized", 403
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM history WHERE id=%s", (log_id,))
        conn.commit()
        return "Deleted", 200
    except Exception:
        conn.rollback()
        return "Error", 500
    finally:
        cur.close()
        conn.close()

# ---------- SOCKET.IO EVENTS ----------
@socketio.on('join_board')
def handle_join_board(data):
    board_id = data.get('board_id')
    if board_id:
        join_room(f'board_{board_id}')

@socketio.on('leave_board')
def handle_leave_board(data):
    board_id = data.get('board_id')
    if board_id:
        leave_room(f'board_{board_id}')

@socketio.on('join_dashboard')
def join_dashboard():
    join_room('dashboard')


if __name__ == '__main__':
    socketio.run(app, debug=True)

