import os, sys, subprocess, shlex, zipfile, traceback

from PySide6.QtWidgets import *
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap

from PIL import Image, ImageDraw, ImageFont
import io

import json

import resources_rc
# pyside6-rcc resources.qrc -o resources_rc.py

from difflib import SequenceMatcher


image_size_limits = [400, 600]
similarity_limit = 0.6


def string_similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()



class ImageDropArea(QLabel):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.pixmap = None
        self.image_path = None
        self.default_text = "Drag and drop image here\n only images from windows path"
        self.default_style = "QLabel { border: 2px dashed gray; }"

        self.reset()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            self.image_path = url.toLocalFile()
            self.load_image()
            break
        event.accept()

    def load_image(self):
        if self.image_path:
            self.pixmap = QPixmap(self.image_path)
            if not self.pixmap.isNull():
                scaled_pixmap = self.pixmap.scaledToWidth(200)
                self.setPixmap(scaled_pixmap)
                self.setStyleSheet("")
            else:
                print(f"Failed to load image from {self.image_path}")
                self.reset()

    def reset(self):
        self.clear()
        self.setText(self.default_text)
        self.setStyleSheet(self.default_style)
        self.image_path = None
        self.pixmap = None

    def get_image_path(self):
        return self.image_path

    def add_text_to_image(self, text):
        if self.image_path:
            try:
                # Open the image using Pillow
                img = Image.open(self.image_path)
                
                
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
                
                # Calculate font size based on image dimensions
                font_size = max(20, min(img.width // 20, img.height // 10))
                
                
                # Wrap text if it's too long
                lines = []
                words = text.split()
                current_line = ""
                for word in words:
                    if len(current_line) + len(word) + 1 > 60:
                        lines.append(current_line.strip())
                        current_line = word
                    else:
                        current_line += " " + word if current_line else word
                lines.append(current_line.strip())
                
                pix_size = int(max(100, len(lines) * font_size * 1.3))
                
                # Create a new image with extra space at the top for text
                total_height = img.height + pix_size  # Add pix_size pixels for text
                new_img = Image.new('RGB', (img.width, total_height), color='white')
                new_img.paste(img, (0, pix_size))  # Paste the original image below the text area
                
                # Create a drawing context
                draw = ImageDraw.Draw(new_img)
                
                # Choose a font (you may need to adjust the font path)
                font = ImageFont.truetype("arial.ttf", font_size)
                
                # Calculate text position
                margin = 10
                x = margin
                y = margin
                
                
                # Draw text on the image
                for line in lines:
                    draw.text((x, y), line, fill=(0, 0, 0), font=font)
                    y += font.size + 5  # Assuming font.size gives the height of the text
                
                # Save the modified image to a BytesIO object
                buffer = io.BytesIO()
                new_img.save(buffer, format="PNG")
                buffer.seek(0)
                
                return buffer.getvalue()
            
            except Exception as e:
                error_message = f"Error adding text to image: {str(e)}"
                QMessageBox.critical(self.parent(), "Image Processing Error", error_message)
                return None
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

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        self.layout = QHBoxLayout()
        self.central_widget.setLayout(self.layout)
        
        # Left side: List of questions
        self.left_widget = QWidget()
        self.left_widget.setMaximumWidth(200)
        self.left_layout = QVBoxLayout()
        self.left_widget.setLayout(self.left_layout)
        
        self.question_list = QListWidget()
        self.add_question_button = QPushButton("New Question")
        self.left_layout.addWidget(self.question_list)
        self.left_layout.addWidget(self.add_question_button)
        
        self.remove_question_button = QPushButton("Remove Question")
        self.left_layout.addWidget(self.remove_question_button)
        
        self.download_button = QPushButton("Download ZIP")
        self.download_button.clicked.connect(self.download_zip)
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
        image_layout.addWidget(self.image_drop_area)

        self.delete_button = QPushButton("Delete\nImage")
        self.delete_button.setFixedHeight(50)
        self.delete_button.setFixedWidth(50)
        self.delete_button.clicked.connect(self.image_drop_area.reset)
        image_layout.addWidget(self.delete_button)

        self.similar_question_label = QLabel("")
        self.similar_question_label.setStyleSheet("color: red;")
        image_layout.addWidget(self.similar_question_label)

        # Add the horizontal layout to the right layout
        self.right_layout.addLayout(image_layout)


        self.answer_hint = QLabel("Enter answers:")
        self.right_layout.addWidget(self.answer_hint)
        
        self.answer_container = QVBoxLayout()
        self.answer_container.setAlignment(Qt.AlignTop)
        self.right_layout.addLayout(self.answer_container)
        
        self.answer_fields = []
        self.add_answer_field()
        
        self.layout.addWidget(self.left_widget)
        self.layout.addLayout(self.right_layout)
        
        self.connect_signals()


    def download_zip(self):
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Zip File",
            "",
            "Zip Files (*.zip)"
        )
        if filename:
            try:
                # Ensure the filename ends with .zip
                if not filename.lower().endswith('.zip'):
                    filename += '.zip'

                # Create the zip file
                with zipfile.ZipFile(filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    # Process each question
                    
                    folder_name = os.path.basename(filename).split('.')[0]

                    for question_number, question_data in self.questions_list.items():
                        for question, answers in question_data.items():
                            # Generate the content for the txt file
                            
                            image_name = ''
                            
                            if question_number in self.images:
                                image_path = self.images[question_number]
                                if os.path.exists(image_path):
                                    image_name = f"{question_number}.png"
                                    zip_file_name = os.path.join(folder_name, image_name)
                                    
                                    # Add text to image and write directly to zip
                                    image_data = self.image_drop_area.add_text_to_image(question)
                                    if image_data:
                                        zipf.writestr(zip_file_name, image_data)

                            
                            content = []
                            correct_answers = [i for i, (_, is_correct) in enumerate(answers) if is_correct]
                            correct_line = f"X{''.join(str(int(i in correct_answers)) for i in range(len(answers)))}"[:-1]
                            content.append(correct_line + "\n")  # Correct answers line
                            if image_name != '':
                                content.append(f'[img]{image_name}[/img]')
                            content.append(f"{question}\n")  # The question itself
                            
                            # Process answers
                            for answer, _ in answers:
                                content.append(f"{answer}\n")
                            
                            # Join the content and encode it
                            file_content = "".join(content).encode('utf-8')
                            
                            # Write the content to the zip file
                            zip_file_name = os.path.join(folder_name, f"{question_number}.txt")
                            zipf.writestr(zip_file_name, file_content)
                            

                            

                print(f"Zip file saved successfully: {filename}")
            except Exception as e:
                error_message = f"Error adding text to image: {str(e)}"
                QMessageBox.critical(self.parent(), "Image Processing Error", error_message)
        else:
            print("File saving cancelled")


    def update_similar_question(self, current_question):
        similar_question = ""
        for qid, data in self.questions_list.items():
            for question, _ in data.items():
                if qid != self.question_no and string_similarity(current_question.lower(), question.lower()) >= similarity_limit:
                    similar_question += f'\n    [{qid}]:{(question[:45] + "...") if len(question) > 45 else question}'
                    # break
            # if similar_question:
            #     break
        
        if similar_question:
            self.similar_question_label.setText(f"Question similar to:  {similar_question}")
        else:
            self.similar_question_label.setText("")


    def update_answer_inputs(self):
        while len(self.answer_fields) > 1 and all(field.text_edit.text().strip() == '' for field in self.answer_fields[-2:]):
            widget = self.answer_container.takeAt(len(self.answer_fields) - 1).widget()
            if widget:
                widget.deleteLater()
            self.answer_fields.pop()
        
        if self.answer_fields and self.answer_fields[-1].text_edit.text().strip():
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


    def select_question(self, current, previous):
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
                    image_path = self.images[question_id]
                    if os.path.exists(image_path):
                        self.image_drop_area.image_path = image_path
                        self.image_drop_area.load_image()
                    else:
                        del self.images[question_id]
                        self.image_drop_area.reset()
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
        self.is_changing = False


    def connect_signals(self):
        self.add_question_button.clicked.connect(self.add_question_to_list)
        self.remove_question_button.clicked.connect(self.remove_question)
        self.question_input.textChanged.connect(self.update_questions_dict)
        self.question_list.currentItemChanged.connect(self.select_question)


    def update_questions_dict(self):
        if self.is_changing: return
        
        question = self.question_input.text()
        answers = [(field.text_edit.text(), field.checkbox.isChecked()) for field in self.answer_fields]
        
        self.questions_list[self.question_no] = {question: answers}
        
        self.question_list.clear()
        for key, value in self.questions_list.items():
            for q, answers in value.items():
                self.question_list.addItem(f"{key}: {q}")
        
        if self.image_drop_area.image_path:
            self.images[self.question_no] = self.image_drop_area.image_path
        
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
        
        self.question_list.clear()
        for key, value in self.questions_list.items():
            for question, answers in value.items():
                self.question_list.addItem(f"{key}: {question}")


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
        
        # Update the display of questions_list
        self.question_list.clear()
        for key, value in self.questions_list.items():
            for question, answers in value.items():
                self.question_list.addItem(f"{key}: {question}")
        
        # Clear inputs
        self.clear_inputs()
        self.update_similar_question(question)
        self.is_changing = False


    def clear_inputs(self):
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