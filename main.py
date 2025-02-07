import os, sys, subprocess, shlex, zipfile, traceback

from PySide6.QtWidgets import *
from PySide6.QtCore import Qt, QBuffer, QTimer
from PySide6.QtGui import QIcon, QPixmap

from PIL import Image, ImageDraw, ImageFont
import io

import math
import json
from llm import LLM
import resources_rc
# pyside6-rcc resources.qrc -o resources_rc.py
from threading import Thread
from difflib import SequenceMatcher


image_size_limits = [600, 600]
similarity_limit = 0.6


def string_similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()



def strip_answers_list(answers_list: list[tuple[str, bool]]):
    if len(answers_list) > 0:
        if answers_list[-1][0] == '':
            answers_list.remove(answers_list[-1])


class ImageDropArea(QLabel):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.pixmap = None
        self.pil_image = None
        self.default_text = "Drag and drop image here\nor press Ctrl+V to paste"
        self.default_style = "QLabel { border: 2px dashed gray; }"
        
        self.update_image = lambda: None
        self.reset()
        
        # Enable focus to receive key events
        self.setFocusPolicy(Qt.StrongFocus)

    def keyPressEvent(self, event):
        # Check for Ctrl+V
        if event.key() == Qt.Key_V and event.modifiers() == Qt.ControlModifier:
            clipboard = QApplication.clipboard()
            mime_data = clipboard.mimeData()
            
            if mime_data.hasImage():
                qimage = clipboard.image()
                if not qimage.isNull():
                    # Convert QImage to PIL Image
                    buffer = QBuffer()
                    buffer.open(QBuffer.ReadWrite)
                    qimage.save(buffer, "PNG")
                    buffer.seek(0)
                    try:
                        self.pil_image = Image.open(io.BytesIO(buffer.data()))
                        self.load_image()
                        self.update_image()
                    except Exception as e:
                        print(f"Failed to convert clipboard image: {str(e)}")
                    finally:
                        buffer.close()

    def dragEnterEvent(self, event):
        mime_data = event.mimeData()
        if mime_data.hasUrls() or mime_data.hasImage() or mime_data.hasFormat('image/png') or mime_data.hasFormat('image/jpeg'):
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        mime_data = event.mimeData()
        
        if mime_data.hasUrls():
            for url in mime_data.urls():
                file_path = url.toLocalFile()
                try:
                    self.pil_image = Image.open(file_path)
                    self.load_image()
                    break
                except Exception as e:
                    print(f"Failed to load image from URL: {str(e)}")
        elif mime_data.hasImage():
            qimage = mime_data.imageData()
            if qimage:
                buffer = QBuffer()
                buffer.open(QBuffer.ReadWrite)
                qimage.save(buffer, "PNG")
                buffer.seek(0)
                try:
                    self.pil_image = Image.open(io.BytesIO(buffer.data()))
                    self.load_image()
                except Exception as e:
                    print(f"Failed to convert QImage to PIL Image: {str(e)}")
        elif mime_data.hasFormat('image/png') or mime_data.hasFormat('image/jpeg'):
            image_data = mime_data.data('image/png') if mime_data.hasFormat('image/png') else mime_data.data('image/jpeg')
            try:
                self.pil_image = Image.open(io.BytesIO(image_data))
                self.load_image()
            except Exception as e:
                print(f"Failed to load image from raw data: {str(e)}")
        
        event.accept()
        self.update_image()

    def load_image(self):
        if self.pil_image:
            # Convert PIL image to QPixmap
            img_byte_arr = io.BytesIO()
            self.pil_image.save(img_byte_arr, format='PNG')
            img_byte_arr = img_byte_arr.getvalue()
            
            self.pixmap = QPixmap()
            self.pixmap.loadFromData(img_byte_arr)
            
            if not self.pixmap.isNull():
                scaled_pixmap = self.pixmap.scaledToWidth(200)
                self.setPixmap(scaled_pixmap)
                self.setStyleSheet("")
            else:
                print("Failed to convert PIL image to QPixmap")
                self.reset()


    def reset(self):
        self.clear()
        self.setText(self.default_text)
        self.setStyleSheet(self.default_style)
        self.pixmap = None
        self.pil_image = None


    def calculate_text_height(self, text, img_width):
        """Calculate the height needed for text area based on image width and text content"""
        try:
            # Calculate font size based on image dimensions
            font_size = max(20, min(img_width // 20, 60))
            font = ImageFont.truetype("arial.ttf", font_size)
            
            # Wrap text if it's too long
            lines = []
            words = text.split()
            current_line = ""
            for word in words:
                if len(current_line) + len(word) + 1 > 40:
                    lines.append(current_line.strip())
                    current_line = word
                else:
                    current_line += " " + word if current_line else word
            lines.append(current_line.strip())
            
            # Calculate height needed for text
            return int(max(100, len(lines) * font_size * 1.3))
        except Exception:
            return 100  # Default height if calculation fails

    def add_text_to_image(self, text):
        try:
            img = self.pil_image.copy()
            
            if img.width < image_size_limits[0] or img.height < image_size_limits[0]:
                scale_factor = max(image_size_limits[0] / img.width, image_size_limits[0] / img.height)
                new_width = int(img.width * scale_factor)
                new_height = int(img.height * scale_factor)
                img = img.resize((new_width, new_height))
                
            if img.width > image_size_limits[1] or img.height > image_size_limits[1]:
                scale_factor = min(image_size_limits[1] / img.width, image_size_limits[1] / img.height)
                new_width = int(img.width * scale_factor)
                new_height = int(img.height * scale_factor)
                img = img.resize((new_width, new_height))
            
            # Calculate font size and text height
            font_size = max(20, min(img.width // 20, img.height // 10))
            font = ImageFont.truetype("arial.ttf", font_size)
            text_height = self.calculate_text_height(text, img.width)
            
            # Create a new image with extra space at the top for text
            total_height = img.height + text_height
            new_img = Image.new('RGB', (img.width, total_height), color='white')
            new_img.paste(img, (0, text_height))
            
            # Create a drawing context
            draw = ImageDraw.Draw(new_img)
            
            # Wrap and draw text
            lines = []
            words = text.split()
            current_line = ""
            for word in words:
                if len(current_line) + len(word) + 1 > 40:
                    lines.append(current_line.strip())
                    current_line = word
                else:
                    current_line += " " + word if current_line else word
            lines.append(current_line.strip())
            
            # Draw text
            margin = 10
            x = margin
            y = margin
            for line in lines:
                draw.text((x, y), line, fill=(0, 0, 0), font=font)
                y += font.size + 5
            
            # Save the modified image
            buffer = io.BytesIO()
            new_img.save(buffer, format="PNG")
            buffer.seek(0)
            
            return buffer.getvalue()
        
        except Exception as e:
            error_message = f"Error adding text to image: {str(e)}"
            QMessageBox.critical(self.parent(), "Image Processing Error", error_message)
            return None

    def remove_text_area(self, image, text):
        """Remove the text area from an image that was previously added with add_text_to_image"""
        try:
            # Calculate the height of text area that was added
            text_height = self.calculate_text_height(text, image.width)
            
            # Crop the image to remove the text area
            return image.crop((0, text_height, image.width, image.height))
        except Exception as e:
            print(f"Error removing text area: {str(e)}")
            return image



class ExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Download")
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.zip_button = QPushButton("  Download ZIP  ")
        self.json_button = QPushButton("  Download JSON  ")

        self.layout.addWidget(self.zip_button)
        self.layout.addWidget(self.json_button)

        self.zip_button.clicked.connect(lambda: self.done(1))
        self.json_button.clicked.connect(lambda: self.done(2))

    def exec(self):
        result = super().exec()
        if result == 1:
            return "ZIP"
        elif result == 2:
            return "JSON"
        return None


class AnswerField(QWidget):
    def __init__(self):
        super().__init__()
        self.layout = QHBoxLayout()
        self.setLayout(self.layout)
        
        self.checkbox = QCheckBox()
        self.text_edit = QLineEdit()
        self.text_edit.setFixedHeight(30)
        
        self.layout.addWidget(self.checkbox)
        self.layout.addWidget(self.text_edit)
        self.setFixedHeight(60)

    def updated(self, function):
        self.text_edit.textChanged.connect(function)
        self.checkbox.stateChanged.connect(function)


class SettingsDialog(QDialog):
    def __init__(self, llm):
        super().__init__()
        self.setWindowTitle("Settings")
        self.llm = llm
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        
        self.llm_group = QGroupBox("LLM Answer Fill Settings")
        self.llm_layout = QVBoxLayout()
        self.llm_group.setLayout(self.llm_layout)
        
        self.url_label = QLabel("API URL:")
        self.url_input = QLineEdit(self.llm.url)
        self.key_label = QLabel("API Key:")
        self.key_input = QLineEdit(self.llm.key)
        self.model_label = QLabel("Model:")
        self.model_input = QLineEdit(self.llm.model)
        self.count_label = QLabel("Answer count:")
        self.count_input = QLineEdit(self.llm.count)
        
        self.llm_layout.addWidget(self.url_label)
        self.llm_layout.addWidget(self.url_input)
        self.llm_layout.addWidget(self.key_label)
        self.llm_layout.addWidget(self.key_input)
        self.llm_layout.addWidget(self.model_label)
        self.llm_layout.addWidget(self.model_input)
        self.llm_layout.addWidget(self.count_label)
        self.llm_layout.addWidget(self.count_input)
        
        self.layout.addWidget(self.llm_group)
        
        self.button_box = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton("Cancel")
        self.button_box.addWidget(self.ok_button)
        self.button_box.addWidget(self.cancel_button)
        self.layout.addLayout(self.button_box)
        
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

    def accept(self):
        self.llm.url = self.url_input.text().strip()
        self.llm.key = self.key_input.text().strip()
        self.llm.model = self.model_input.text().strip()
        self.llm.count = self.count_input.text().strip()
        self.llm.save_json()
        super().accept()



class TestownikCreator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Testownik Creator")
        self.setWindowIcon(QIcon(":logo.png"))
        self.setGeometry(100, 100, 800, 600)
        self.questions_list = {}
        self.question_no = 0
        self.is_changing = False
        self.images = {}
        self.llm = LLM()
        self.llm.load_json()
        
        
        

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        self.layout = QHBoxLayout()
        self.central_widget.setLayout(self.layout)
        
        # Left side: List of questions
        self.left_widget = QWidget()
        self.left_widget.setMaximumWidth(200)
        self.left_layout = QVBoxLayout()
        self.left_widget.setLayout(self.left_layout)
        
        
        # Add settings action
        self.settings_action = QPushButton("Settings")
        self.settings_action.clicked.connect(self.show_settings)
        self.left_layout.addWidget(self.settings_action)
        
        
        self.import_button = QPushButton("Import test")
        self.import_button.clicked.connect(self.import_test)
        self.left_layout.addWidget(self.import_button)
        
        self.question_list = QListWidget()
        self.add_question_button = QPushButton("New Question")
        self.left_layout.addWidget(self.question_list)
        self.left_layout.addWidget(self.add_question_button)
        
        self.remove_question_button = QPushButton("Remove Question")
        self.left_layout.addWidget(self.remove_question_button)
        
        self.download_button = QPushButton("Download test")
        self.download_button.clicked.connect(self.download_file)
        self.left_layout.addWidget(self.download_button)
        
        # Right side: Question input area
        self.right_layout = QVBoxLayout()
        self.right_layout.setAlignment(Qt.AlignTop)
        
        self.question_hint = QLabel("Enter your question:")
        self.question_input = QLineEdit()
        self.question_input.setMinimumHeight(60)
        self.right_layout.addWidget(self.question_hint)
        self.right_layout.addWidget(self.question_input)
        
        # Create a horizontal layout for the image drop area and delete button
        image_layout = QHBoxLayout()
        image_layout.setAlignment(Qt.AlignTop)

        self.image_drop_area = ImageDropArea()
        self.image_drop_area.setAlignment(Qt.AlignCenter)
        self.image_drop_area.setFixedWidth(200)
        self.image_drop_area.setMinimumHeight(100)
        self.image_drop_area.update_image = self.update_answer_field
        image_layout.addWidget(self.image_drop_area)

        self.delete_button = QPushButton("Delete\nImage")
        self.delete_button.setFixedHeight(50)
        self.delete_button.setFixedWidth(50)
        self.delete_button.clicked.connect(self.delete_image)
        image_layout.addWidget(self.delete_button)
        
        self.similar_question_label = QTextBrowser()
        self.similar_question_label.setReadOnly(True)
        self.similar_question_label.setStyleSheet("background-color: transparent; border: none;")
        self.similar_question_label.setHtml("")
        self.similar_question_label.setFixedHeight(100)
        
        image_layout.addWidget(self.similar_question_label)

        # Add LLM fill button
        self.llm_fill_button = QPushButton("✨")
        self.llm_fill_button.setFixedSize(30, 30)
        self.llm_fill_button.clicked.connect(self.llm_click)
        image_layout.addWidget(self.llm_fill_button)
        
        # Add the horizontal layout to the right layout
        self.right_layout.addLayout(image_layout)

        self.answer_hint = QLabel("Enter answers:")
        self.right_layout.addWidget(self.answer_hint)
        
        self.answer_container = QVBoxLayout()
        self.answer_container.setAlignment(Qt.AlignTop)
        self.right_layout.addLayout(self.answer_container)
        self.right_layout.addStretch()
        
        self.answer_fields = []
        self.add_answer_field()
        
        self.layout.addWidget(self.left_widget)
        self.layout.addLayout(self.right_layout)
        
        self.connect_signals()


    def _check_llm_status(self):
        if self.llm_status:
            self.polling_timer.stop()
            self.reselect_question()
            self.llm_fill_button.setText('✨')
        if type(self.llm_status) != str: return
        if self.llm_status == "Please enter a question first":
            QMessageBox.warning(self, "Warning", "Please enter a question first")
        else:
            QMessageBox.warning(self, "LLM Error", self.llm_status)
            

    def llm_click(self):
        self.llm_status = False
        self.llm_fill_button.setText('💭')
        
        self.llm_thread = Thread(target=self.fill_answers_with_llm)
        self.llm_thread.start()
        
        self.polling_timer = QTimer(self)
        self.polling_timer.timeout.connect(self._check_llm_status)
        self.polling_timer.start(100)  # Check every 100ms


    def fill_answers_with_llm(self):
        """Generate answers using the LLM"""
        if not self.question_input.text().strip():
            self.llm_status = "Please enter a question first, and one correct answer"
            return
        try:
            question = list(self.questions_list[self.question_no].keys())[0]
            answers_list: list = self.questions_list[self.question_no][question]
            strip_answers_list(answers_list)
            
            if len(answers_list) != 1:
                self.llm_status = "Please enter a question first, and one correct answer"
                return
            answers = self.llm.generate_answers(question, answers_list[0][0])
            
            is_true = False
            for index, i in enumerate(answers_list):
                if i[1]: is_true = True
            if not is_true: answers_list[0] = (answers_list[0][0], True)
            for answer in answers:
                answers_list.append((answer, False))
            
            
        except Exception as e:
            self.llm_status = traceback.format_exc()
            return
        self.llm_status = True


    def show_settings(self):
        """Display and edit settings"""
        dialog = SettingsDialog(self.llm)
        if dialog.exec():
            QMessageBox.information(self, "Settings Saved", "Settings have been saved")


    def reselect_question(self):
        
        self.is_changing = True
        for i in range(self.question_list.count()):
            item = self.question_list.item(i)
            if int(item.text().split(':')[0]) == self.question_no:
                self.select_question(item, force = True)
        self.is_changing = False


    def download_file(self):
        filename, ext = QFileDialog.getSaveFileName(
            self,
            "Download test",
            "",
            "Zip Files (*.zip);;JSON Files (*.json)"
        )

        if filename:
            if ext == "Zip Files (*.zip)":
                self.export_as_zip(filename)
            elif ext == "JSON Files (*.json)":
                self.export_as_json(filename)
        else:
            print("Export cancelled")


    def export_as_zip(self, filename):
        try:
            # Ensure the filename ends with .zip
            if not filename.lower().endswith('.zip'):
                filename += '.zip'

            # Create the zip file
            with zipfile.ZipFile(filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Process each question
                
                folder_name = os.path.basename(filename).split('.')[0]

                for question_number, question_data in self.questions_list.items():
                    question, answers = list(question_data.items())[0]
                    
                    # skip if question is empty or there are no answers, unless there is an image
                    if (len(question) < 2 and question_number not in self.images) or len(answers) < 1: continue
                    
                    image_name = ''
                    
                    if question_number in self.images:
                        image = self.images[question_number]
                        
                        image_name = f"{question_number}.png"
                        zip_file_name = os.path.join(folder_name, image_name)
                        
                        # Add text to image and write directly to zip
                        if question.strip() != '':  # Only add text if the question is not empty
                            self.image_drop_area.pil_image = image
                            image_data = self.image_drop_area.add_text_to_image(question)
                            self.image_drop_area.pil_image = None
                        else:
                            # Save image without text
                            buffer = io.BytesIO()
                            image.save(buffer, format='PNG')
                            image_data = buffer.getvalue()
                            buffer.close()
                        
                        zipf.writestr(zip_file_name, image_data)

                    num_answers = 0
                    for answer, _ in answers:
                        if answer.strip() != '':
                            num_answers += 1
                    
                    content = []
                    correct_answers = [i for i, (_, is_correct) in enumerate(answers) if is_correct]
                    correct_line = f"X{''.join(str(int(i in correct_answers)) for i in range(num_answers))}"
                    content.append(correct_line + "\n")  # Correct answers line
                    if image_name != '':
                        content.append(f'[img]{image_name}[/img] ')
                    content.append(f"{question}\n")  # The question itself
                    
                    # Process answers
                    for answer, _ in answers:
                        if answer.strip() != '':
                            content.append(f"{answer}\n")
                    
                    # Join the content and encode it
                    file_content = "".join(content).encode('utf-8')
                    
                    # Write the content to the zip file
                    zip_file_name = os.path.join(folder_name, f"{question_number}.txt")
                    zipf.writestr(zip_file_name, file_content)


                print(f"Zip file saved successfully: {filename}")
        except Exception as e:
            error_message = f"Error creating zip file: {str(e)}"
            QMessageBox.critical(self.parent(), "Zip Creation Error", error_message)


    def export_as_json(self, filename):
        try:
            # Ensure the filename ends with .json
            if not filename.lower().endswith('.json'):
                filename += '.json'

            quiz_data = {
                "title": os.path.basename(filename).split('.')[0],
                "description": "Made with Testownik Creator by *Matszwe02*",
                "questions": []
            }

            for question_number, question_data in self.questions_list.items():
                for question, answers in question_data.items():
                    if len(question) < 2 or len(answers) < 1: continue
                    
                    correct_count = sum(corr for _, corr in answers)
                    quiz_data["questions"].append({
                        "question": question,
                        "answers": [{"answer": ans, "correct": corr} for ans, corr in answers if ans.strip() != ""],
                        "multiple": correct_count > 1
                    })

            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(quiz_data, f, ensure_ascii=False, indent=4)

            print(f"JSON file saved successfully: {filename}")
        except Exception as e:
            error_message = f"Error creating JSON file: {str(e)}"
            QMessageBox.critical(self.parent(), "JSON Creation Error", error_message)


    def update_similar_question(self, current_question):
        similar_questions = []
        for qid, data in self.questions_list.items():
            for question, _ in data.items():
                if qid != self.question_no:
                    similarity = string_similarity(current_question.lower(), question.lower())
                    if similarity >= similarity_limit:
                        similar_questions.append((qid, question, similarity))

        if similar_questions:
            html_output = "<p>Similar questions:</p><ul>"
            for qid, question, similarity in similar_questions:
                # Map similarity to a color between red and green
                g = int(255 * (0.9-similarity**6))
                color = f"rgb(255, {min(max(g,0),255)}, 0)"
                
                # Create a tooltip with the full question
                
                desc = question + '\n'
                
                for answer, correct in self.questions_list[qid][question]:
                    desc += '☑' if correct else '☐'
                    desc += answer.strip() + '\n'
                
                tooltip = f'<span title="{desc}">{question}</span>'
                
                html_output += f'<li style="color: {color};">[{qid}]: {tooltip}</li>'
            html_output += "</ul>"
            
            
            self.similar_question_label.setText(html_output)
        else:
            self.similar_question_label.setText("")


    def import_test(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Import Test",
            "",
            "Zip Files (*.zip)"
        )

        if filename:
            try:
                self.import_from_zip(filename)
            except Exception as e:
                error_message = f"Error importing test: {traceback.format_exc()}"
                QMessageBox.critical(self, "Import Error", error_message)
                traceback.print_exc()


    def import_from_zip(self, filename):
        self.questions_list.clear()
        self.images.clear()
        self.question_list.clear()

        with zipfile.ZipFile(filename, 'r') as zip_ref:
            # First pass: Process text files to get questions and answers
            for file_info in zip_ref.infolist():
                if file_info.filename.endswith('.txt'):
                    try:
                        # Get question ID from filename (assuming format like "1.txt")
                        base_name = os.path.basename(file_info.filename)
                        question_id = int(os.path.splitext(base_name)[0])
                        
                        with zip_ref.open(file_info) as file:
                            # Try to decode with utf-8 and fallback to iso-8859-1
                            content = file.read()
                            try:
                                decoded_content = content.decode('utf-8').strip()
                            except UnicodeDecodeError:
                                try:
                                    decoded_content = content.decode('windows-1250').strip()
                                except UnicodeDecodeError:
                                    decoded_content = content.decode('iso-8859-1').strip()
                            lines = decoded_content.split('\n')
                            if len(lines) < 3: continue
                            
                            # Extract correct answers
                            correct_answers = []
                            if lines[0].startswith('X'):
                                correct_answers = [int(x) for x in (lines[0][1:]).strip()]
                            
                            # Find the question line and check for image reference
                            question = lines[1].split('[/img]')[-1].strip()
                            
                            # Extract answers
                            answers = []
                            for i, line in enumerate(lines[2:]):
                                if line.strip():
                                    answers.append((line.strip(), (correct_answers[i] == 1) if (len(correct_answers) >= i+1) else False))
                            
                            self.questions_list[question_id] = {question: answers}
                            # self.question_list.addItem(f"{question_id}: {question}")
                    except Exception as e:
                        print(f"Error processing text file {file_info.filename}: {str(e)}")
            
            # Second pass: Process image files
            for file_info in zip_ref.infolist():
                if file_info.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                    try:
                        # Get question ID from filename (assuming format like "1.png")
                        base_name = os.path.basename(file_info.filename)
                        question_id = int(os.path.splitext(base_name)[0])
                        
                        # Read image data and create PIL Image
                        with zip_ref.open(file_info) as image_file:
                            image_data = image_file.read()
                            image = Image.open(io.BytesIO(image_data))
                            
                            # If this question has text, remove the text area from the image
                            if question_id in self.questions_list:
                                question = list(self.questions_list[question_id].keys())[0]
                                if question.strip():
                                    image = self.image_drop_area.remove_text_area(image, question)
                            
                            self.images[question_id] = image
                    except Exception as e:
                        print(f"Error processing image {file_info.filename}: {str(e)}")

        self.question_no = list(self.questions_list.keys())[0] or 0
        self.update_question_list()

        QMessageBox.information(self, "Import Success", "Test imported successfully!")


    def update_answer_inputs(self):
        while len(self.answer_fields) > 1 and all(field.text_edit.text().strip() == '' for field in self.answer_fields[-2:]):
            widget = self.answer_container.takeAt(len(self.answer_fields) - 1).widget()
            if widget:
                widget.deleteLater()
            self.answer_fields.pop()
        
        if self.answer_fields and self.answer_fields[-1].text_edit.text().strip():
            self.add_answer_field()
        elif not self.answer_fields:
            self.add_answer_field()


    def update_answer_field(self):
        self.update_answer_inputs()
        self.update_questions_dict()

    def add_answer_field(self, text = "", is_correct = False):
        new_field = AnswerField()
        new_field.text_edit.setText(text)
        new_field.checkbox.setChecked(is_correct)
        new_field.updated(self.update_answer_field)
        self.answer_container.addWidget(new_field)
        self.answer_fields.append(new_field)
        return new_field


    def delete_image(self):
        self.image_drop_area.reset()
        self.update_answer_field()


    def select_question(self, current, previous = 0, force=False):
        if self.is_changing and not force: return
        self.is_changing = True
        if current:
            selected_text = current.text()
            question_id = int(selected_text.split(':')[0])
            self.question_no = question_id
            self.question_hint.setText(f"Enter your question: [{self.question_no}]")
            
            question_data = self.questions_list[question_id]
            for question, answers in question_data.items():
                self.question_input.setText(question)
                
                
                if question_id in self.images:
                    image = self.images[question_id]
                    self.image_drop_area.pil_image = image
                    self.image_drop_area.load_image()
                else:
                    self.image_drop_area.reset()

                
                # Remove existing answer fields
                while self.answer_fields:
                    widget = self.answer_container.takeAt(0).widget()
                    if widget:
                        widget.deleteLater()
                    self.answer_fields.pop()
                
                # Add new answer fields
                id = 0
                for answer, is_correct in answers:
                    id += 1
                    new_field = self.add_answer_field(answer, is_correct)

            self.update_similar_question(current.text())
            self.update_answer_inputs()
        self.is_changing = False


    def connect_signals(self):
        self.add_question_button.clicked.connect(self.add_question_to_list)
        self.remove_question_button.clicked.connect(self.remove_question)
        self.question_input.textChanged.connect(self.update_questions_dict)
        self.question_list.currentItemChanged.connect(self.select_question)


    def update_question_item(self, item: QListWidgetItem, key, question, answers):
        item.setText(f"{key}: {'🗎 ' if key in self.images.keys() else ''}{question}")
        desc = question + '\n'
        for answer, correct in answers:
            desc += '☑' if correct else '☐'
            desc += answer.strip() + '\n'
        item.setToolTip(desc)
        return item


    def update_question_list(self):
        if self.question_list.count() != len(self.questions_list):
            self.question_list.clear()
            for key, value in self.questions_list.items():
                for question, answers in value.items():
                    self.question_list.addItem(self.update_question_item(QListWidgetItem(), key, question, answers))
        else:
            for i in range(self.question_list.count()):
                item = self.question_list.item(i)
                key = int(item.text().split(':')[0])
                question = list(self.questions_list[key].keys())[0]
                answers = list(self.questions_list[key].values())[0]
                self.update_question_item(item, key, question, answers)


    def update_questions_dict(self):
        if self.is_changing: return
        
        question = self.question_input.text().strip().replace('\n', ' ').replace('\t', '  ').replace('\r', '')
        answers = [(field.text_edit.text().strip().replace('\n', ' ').replace('\t', '  ').replace('\r', ''), field.checkbox.isChecked()) for field in self.answer_fields]
        
        self.questions_list[self.question_no] = {question: answers}
        self.update_question_list()
        
        if self.image_drop_area.pil_image:
            self.images[self.question_no] = self.image_drop_area.pil_image
        elif self.question_no in self.images:
            del self.images[self.question_no]
        
        self.update_similar_question(question)


    def remove_question(self):
        self.is_changing = True
        self.questions_list.pop(self.question_no, None)
        last_id = 0
        for i in self.questions_list.keys():
            if int(i) > last_id: last_id = i
        self.clear_inputs()
        self.question_no = last_id
        self.question_hint.setText(f"Enter your question: [{self.question_no}]")
        self.is_changing = False
        
        self.update_question_list()


    def add_question_to_list(self):
        self.is_changing = True
        question = ""
        answers = []
        
        # Increment question_no
        last_id = 0
        for i in self.questions_list.keys():
            if int(i) > last_id: last_id = i
        
        self.question_no = last_id + 1
        self.question_hint.setText(f"Enter your question: [{self.question_no}]")
        # Add the new question to questions_list
        self.questions_list[self.question_no] = {question: answers}
        self.update_question_list()
        
        # Clear inputs
        self.clear_inputs()
        self.update_similar_question(question)
        self.is_changing = False


    def clear_inputs(self):
        self.is_changing = True
        self.question_input.setText("")
        for field in self.answer_fields:
            field.text_edit.clear()
            field.checkbox.setChecked(False)
        while len(self.answer_fields) > 1:
            widget = self.answer_container.takeAt(len(self.answer_fields) - 1).widget()
            if widget:
                widget.deleteLater()
            self.answer_fields.pop()
        self.update_questions_dict()
        self.image_drop_area.reset()

        if self.question_no in self.images:
            del self.images[self.question_no]
        self.is_changing = False

    # def save_to_json(self):
        
    #     with open('test.json', 'w') as f:
    #         json.dump(self.questions_list, f, indent=4)

    def closeEvent(self, event):
        # self.save_to_json()
        event.accept()

def main():
    app = QApplication(sys.argv)
    window = TestownikCreator()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    if '--build' in sys.argv:
        subprocess.run(shlex.split('pyinstaller --onefile --clean --name=testownik-creator -y main.py --icon ./logo.png --noconsole --exclude-module "**/*.git" --exclude-module "**/__cache__" --exclude-module "**/dist" --exclude-module "**/build"'))
    elif len(sys.argv) > 1:
        print('Testownik Creator help page\n\n--build     to build project\n\nyeah thats all')
    else:
        main()
