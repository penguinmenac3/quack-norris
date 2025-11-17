import os
import tkinter as tk
from tkinter import scrolledtext


def ask_user_consent(question: str, detail: str | None = None) -> bool:
    """Show a popup with the main question for which we want the users consent.
    Additional details can also be displayed optionally."""
    consent = False
    root = tk.Tk()
    root.withdraw()  # Hide main window
    popup = tk.Toplevel()
    popup.title("User Consent Required")
    icon_path = os.path.join(os.path.dirname(__file__), "../../images/duck_low_res-focus.png")
    icon_img = tk.PhotoImage(file=icon_path)
    popup.iconphoto(True, icon_img)
    popup.lift()
    popup.attributes('-topmost', True)
    # Let geometry fit content, then center
    popup.update_idletasks()
    width = 500
    height = 150
    if detail:
        height = 270
    popup.geometry(f"{width}x{height}")
    # Center the window
    popup.update_idletasks()
    x = (popup.winfo_screenwidth() // 2) - (width // 2)
    y = (popup.winfo_screenheight() // 2) - (height // 2)
    popup.geometry(f"{width}x{height}+{x}+{y}")
    label = tk.Label(popup, text=question, font=("Arial", 12))
    label.pack(pady=10, anchor="n")
    if detail:
        text_area = scrolledtext.ScrolledText(popup, wrap=tk.WORD, width=60, height=8)
        text_area.insert(tk.END, detail)
        text_area.config(state=tk.DISABLED)
        text_area.pack(padx=10, pady=10, anchor="n")
    # Spacer to push buttons to bottom
    spacer = tk.Frame(popup)
    spacer.pack(expand=True, fill="both")
    def on_accept():
        nonlocal consent
        consent = True
        popup.destroy()
    def on_decline():
        nonlocal consent
        consent = False
        popup.destroy()
    btn_frame = tk.Frame(popup)
    btn_frame.pack(pady=10, side="bottom", anchor="s")
    accept_btn = tk.Button(btn_frame, text="Accept", command=on_accept, width=15, bg="green", fg="white")
    accept_btn.pack(side=tk.LEFT, padx=10)
    decline_btn = tk.Button(btn_frame, text="Decline", command=on_decline, width=15, bg="red", fg="white")
    decline_btn.pack(side=tk.LEFT, padx=10)
    popup.grab_set()
    root.wait_window(popup)
    root.destroy()
    return consent


if __name__ == "__main__":
    result = ask_user_consent("Testing?", detail="This is some text\nwith\nmultiple\n\n\n\n\n\nlines")
    print(f"User acceptance: {result}")
