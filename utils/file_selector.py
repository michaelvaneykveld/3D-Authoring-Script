import tkinter as tk
from tkinter import filedialog, messagebox

def _create_hidden_root():
    """Creates a hidden, top-most Tkinter root window."""
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    root.attributes('-topmost', True)  # Keep the dialog on top of other windows
    return root

def select_source_file():
    """
    Opens a graphical file dialog for the user to select a source video file.

    Returns:
        str: The absolute path to the selected file, or an empty string if canceled.
    """
    root = _create_hidden_root()
    try:
        # Open the file dialog and specify common video file types for convenience
        file_path = filedialog.askopenfilename(
            parent=root,
            title="Select Source Video File",
            filetypes=(("Video Files", "*.mkv *.mp4 *.avi *.mov *.ts *.m2ts"), ("All files", "*.*"))
        )
    finally:
        root.destroy()
    return file_path # filedialog returns an empty string if the dialog is canceled

def select_output_directory(title="Select Output Directory"):
    """
    Opens a graphical dialog for the user to select an output directory.

    Returns:
        str: The absolute path to the selected directory, or an empty string if canceled.
    """
    root = _create_hidden_root()
    try:
        dir_path = filedialog.askdirectory(parent=root, title=title)
    finally:
        root.destroy()
    return dir_path

def select_output_iso():
    """
    Opens a graphical dialog for the user to save the final ISO file.

    Returns:
        str: The absolute path for the file to be saved, or an empty string if canceled.
    """
    root = _create_hidden_root()
    try:
        file_path = filedialog.asksaveasfilename(
            parent=root,
            title="Save Blu-ray ISO as...",
            defaultextension=".iso",
            filetypes=(("ISO Image", "*.iso"), ("All files", "*.*"))
        )
    finally:
        root.destroy()
    return file_path

def ask_yes_no(title, message):
    """
    Displays a yes/no messagebox that is always on top.

    Returns:
        bool: True for 'Yes', False for 'No'.
    """
    root = _create_hidden_root()
    try:
        return messagebox.askyesno(parent=root, title=title, message=message)
    finally:
        root.destroy()

def ask_output_type():
    """
    Displays a custom messagebox asking the user to choose between ISO and BDMV.

    Returns:
        str: 'yes' for ISO, 'no' for BDMV. Returns 'cancel' if the dialog is closed.
    """
    root = _create_hidden_root()
    try:
        # askyesnocancel returns True, False, or None.
        # We map this to strings for clarity in the main script.
        result = messagebox.askyesnocancel(
            parent=root,
            title="Select Output Type",
            message="How would you like to save the final Blu-ray?\n\n"
                    "Press 'Yes' to create a single .ISO file.\n"
                    "Press 'No' to create a BDMV folder structure.",
            icon=messagebox.QUESTION
        )
        return 'yes' if result is True else 'no' if result is False else 'cancel'
    finally:
        root.destroy()
