import os
import random
import string
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
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
            return render_template('register.html')
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
    return render_template('register.html')

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
    return render_template('login.html')

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
    conn = get_db_conn(); cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # board
        cur.execute("SELECT b.*, u.username AS owner_name FROM boards b JOIN users u ON b.owner_id=u.id WHERE b.id=%s", (board_id,))
        board = cur.fetchone()
        if not board:
            flash('Board not found', 'error'); return redirect(url_for('dashboard'))
        # check membership: owner or in user_boards
        cur.execute("SELECT 1 FROM user_boards WHERE board_id=%s AND user_id=%s", (board_id, user_id))
        if not cur.fetchone():
            flash('You are not a member of this board', 'error'); return redirect(url_for('dashboard'))
        # members (owner + joined)
        cur.execute("""
            SELECT u.id, u.username
            FROM users u
            JOIN user_boards ub ON ub.user_id = u.id
            WHERE ub.board_id = %s
            ORDER BY u.username
        """, (board_id,))
        members = cur.fetchall()
        # tasks with assigned username
        cur.execute("""
            SELECT t.*, u.username AS assigned_name
            FROM tasks t
            LEFT JOIN users u ON t.assigned_to = u.id
            WHERE t.board_id=%s
            ORDER BY t.created_at DESC
        """, (board_id,))
        tasks = cur.fetchall()
    finally:
        cur.close(); conn.close()
    return render_template('board.html', board=board, members=members, tasks=tasks, user=session['user'])

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
        cur.execute("INSERT INTO tasks (name, description, board_id, assigned_to, comments, due_date) VALUES (%s,%s,%s,%s,%s,%s)",
                    (name, description, board_id, assigned_to, comments, dt_due))
        conn.commit(); flash('Task added', 'success')
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
            cur.execute("UPDATE tasks SET name=%s, description=%s, assigned_to=%s, comments=%s, due_date=%s WHERE id=%s",
                        (name, description, assigned_to, comments, dt_due, task_id))
            conn.commit()
            flash('Task updated', 'success')
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
        conn.commit(); flash('Task deleted', 'success')
    except Exception as e:
        conn.rollback(); flash('Delete task error: '+str(e), 'error')
    finally:
        cur.close(); conn.close()
    return redirect(url_for('board_view', board_id=board_id))

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
    except Exception as e:
        conn.rollback(); flash('Delete board error: '+str(e), 'error')
    finally:
        cur.close(); conn.close()
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)
