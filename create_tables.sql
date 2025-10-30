-- users table (keep your existing users if needed; remove DROP if not needed)
CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  username VARCHAR(100) NOT NULL,
  email VARCHAR(150) UNIQUE NOT NULL,
  password_hash TEXT NOT NULL
);

-- boards table
CREATE TABLE IF NOT EXISTS boards (
  id SERIAL PRIMARY KEY,
  name VARCHAR(200) NOT NULL,
  description TEXT,
  board_code VARCHAR(20) UNIQUE NOT NULL,
  owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- mapping table: which users joined which boards
CREATE TABLE IF NOT EXISTS user_boards (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  board_id INTEGER REFERENCES boards(id) ON DELETE CASCADE
);

-- tasks table
CREATE TABLE IF NOT EXISTS tasks (
  id SERIAL PRIMARY KEY,
  name VARCHAR(200) NOT NULL,
  description TEXT,
  board_id INTEGER REFERENCES boards(id) ON DELETE CASCADE,
  assigned_to INTEGER REFERENCES users(id),
  comments TEXT,
  due_date TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE tasks
ADD COLUMN IF NOT EXISTS position INTEGER DEFAULT 0;

WITH ordered AS (
  SELECT id, ROW_NUMBER() OVER (PARTITION BY board_id ORDER BY created_at, id) AS rn
  FROM tasks
)
UPDATE tasks
SET position = ordered.rn
FROM ordered
WHERE tasks.id = ordered.id;

select * from tasks;

ALTER TABLE tasks
ADD COLUMN IF NOT EXISTS progress_percent INTEGER DEFAULT 0;

CREATE TABLE IF NOT EXISTS history (
  id SERIAL PRIMARY KEY,
  board_id INTEGER REFERENCES boards(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);