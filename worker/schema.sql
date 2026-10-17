-- Daily counters only: no event is stored, and no install id or address is ever written.
CREATE TABLE IF NOT EXISTS counts (
  day   TEXT    NOT NULL,
  event TEXT    NOT NULL,
  field TEXT    NOT NULL,
  value TEXT    NOT NULL,
  n     INTEGER NOT NULL,
  total INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, event, field, value)
);

-- A per-day salted hash of the install id, kept for at most three days, so each install is counted once a day.
CREATE TABLE IF NOT EXISTS visitors (
  day TEXT NOT NULL,
  h   TEXT NOT NULL,
  PRIMARY KEY (day, h)
);
