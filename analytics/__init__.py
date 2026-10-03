"""Offline, metadata-only analytics of Savia/Gloria agent behaviour.

Reads the operational SQLite state read-only and writes a separate analytics
database. It never modifies FLUJO, the chat service or the workflow store.
"""
