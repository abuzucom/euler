def prune_expired(sessions, now):
    for session in sessions:
        if session.expires_at <= now:
            sessions.remove(session)
    return sessions
