import os, smtplib
from email.message import EmailMessage
from typing import List, Optional
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Email")
@mcp.tool()
def send_email(receiver: List[str], subject: str, body: str, attachments: Optional[List[str]] = None) -> str:
    msg = EmailMessage()
    msg['Subject'], msg['From'], msg['To'] = subject, os.getenv("SMTP_FROM", ""), ", ".join(receiver)
    msg.set_content(body)
    try:
        server = smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "587")))
        server.starttls()
        server.login(os.getenv("SMTP_USER", ""), os.getenv("SMTP_PASSWORD", ""))
        server.send_message(msg); server.quit()
        return f"Sent to {', '.join(receiver)}"
    except Exception as e: raise RuntimeError(f"Email Error: {str(e)}")

if __name__ == "__main__": mcp.run()