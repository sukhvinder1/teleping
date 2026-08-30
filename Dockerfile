FROM binwiederhier/ntfy:latest

# Cloud Run injects the port to listen on via $PORT (defaults to 8080).
# ntfy's listen address is set via NTFY_LISTEN_HTTP, so translate $PORT into it at startup.
COPY server/ntfy.yml /etc/ntfy/server.yml

ENV PORT=8080
EXPOSE 8080

ENTRYPOINT ["sh", "-c", "ntfy serve --listen-http :${PORT}"]
