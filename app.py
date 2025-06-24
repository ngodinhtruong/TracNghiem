from docx import Document
import re
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify, session
from flask_sqlalchemy import SQLAlchemy
import os
from werkzeug.utils import secure_filename
import time
import random
from flask_session import Session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

def get_shuffled_order(key, items):
    # key: tên session key, items: list các object có id
    if key in session:
        order = session[key]
    else:
        order = [item.id for item in items]
        random.shuffle(order)
        session[key] = order
        session.modified = True
    # Trả về list object theo thứ tự đã trộn
    id_to_item = {item.id: item for item in items}
    return [id_to_item[i] for i in order if i in id_to_item]

def read_mcq_from_docx(filename):
    doc = Document(filename)
    content = "\n".join([p.text.strip() for p in doc.paragraphs if p.text.strip()])
    
    # Tách các câu hỏi dựa vào số thứ tự đầu dòng (VD: 41. ... 42. ...)
    pattern = r"(\d+\..*?)(?=\n\d+\.|\Z)"  # Match từ số câu đến trước số câu tiếp theo hoặc kết thúc file
    raw_questions = re.findall(pattern, content, re.DOTALL)
    
    questions = []
    for raw in raw_questions:
        lines = raw.strip().split("\n")
        question_line = lines[0]
        options = lines[1:]
        
        question_text = question_line.strip()
        parsed_options = {}
        
        for opt in options:
            # Chấp nhận [<a>] hoặc a. hoặc [<A>]
            match = re.match(r"[\[\(]?[<]?[a-dA-D][>\)]?[\]\.]?\s*(.*)", opt.strip())
            if match:
                label = re.search(r"[a-dA-D]", opt).group(0).upper()
                parsed_options[label] = match.group(1).strip()

        questions.append({
            "question": question_text,
            "options": parsed_options
        })
    
    return questions

def init_db_from_docx(filename, class_name, topic_name):
    db.create_all()
    quiz_class = QuizClass.query.filter_by(name=class_name, user_id=current_user.id).first()
    if not quiz_class:
        quiz_class = QuizClass(name=class_name, user_id=current_user.id)
        db.session.add(quiz_class)
        db.session.commit()
    topic = Topic.query.filter_by(name=topic_name, class_id=quiz_class.id).first()
    if not topic:
        topic = Topic(name=topic_name, class_id=quiz_class.id)
        db.session.add(topic)
        db.session.commit()
    questions = read_mcq_from_docx(filename)
    for q in questions:
        question = Question(text=q['question'], topic_id=topic.id)
        db.session.add(question)
        db.session.flush()
        for label, text in q['options'].items():
            is_correct = (label == 'A')
            option = Option(label=label, text=text, is_correct=is_correct, question_id=question.id)
            db.session.add(option)
    db.session.commit()

# Demo
questions = read_mcq_from_docx("q1.docx")


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'quiz.db')
app.secret_key = 'your-very-secret-key-1234567890'
# Sử dụng Flask-Session để lưu session vào file
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = './flask_session/'
app.config['SESSION_PERMANENT'] = False
Session(app)
db = SQLAlchemy(app)

# Định nghĩa các model
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    first_name = db.Column(db.String(50), nullable=True)
    last_name = db.Column(db.String(50), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    # Thêm các trường mở rộng nếu muốn (first_name, last_name, phone)
    quiz_classes = db.relationship('QuizClass', backref='user', lazy=True)

class QuizClass(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    topics = db.relationship('Topic', backref='quiz_class', lazy=True)

class Topic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('quiz_class.id'), nullable=False)
    questions = db.relationship('Question', backref='topic', lazy=True)

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    options = db.relationship('Option', backref='question', lazy=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('topic.id'), nullable=False)

class Option(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(1), nullable=False)
    text = db.Column(db.Text, nullable=False)
    is_correct = db.Column(db.Boolean, default=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)

class WrongAnswer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(128), nullable=False)
    class_id = db.Column(db.Integer, nullable=False)
    topic_id = db.Column(db.Integer, nullable=False)
    question_id = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())

class QuizScore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(128), nullable=False)
    class_id = db.Column(db.Integer, nullable=False)
    topic_id = db.Column(db.Integer, nullable=False)
    score = db.Column(db.Float, nullable=False)  # Percentage score
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())

# Cấu hình Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Route đăng ký
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('menu'))
    if request.method == 'POST':
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        phone = request.form.get('phone')
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        if password != confirm_password:
            flash('Mật khẩu nhập lại không khớp!')
            return redirect(url_for('register'))
        if User.query.filter_by(username=username).first():
            flash('Tên đăng nhập đã tồn tại!')
            return redirect(url_for('register'))
        # Lưu thêm họ, tên, số điện thoại nếu muốn (cần thêm cột vào model User)
        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            first_name=first_name,
            last_name=last_name,
            phone=phone
        )
        db.session.add(user)
        db.session.commit()
        flash('Đăng ký thành công! Hãy đăng nhập.')
        return redirect(url_for('login'))
    return render_template('register.html')

# Route đăng nhập
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('menu'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('menu'))
        else:
            flash('Sai tên đăng nhập hoặc mật khẩu!')
            return redirect(url_for('login'))
    return render_template('login.html')

# Route đăng xuất
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Bảo vệ các route chính (menu, quiz, edit, ...)
def login_required_view(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Áp dụng login_required_view cho các route chính
@app.route('/menu')
@login_required_view
def menu():
    for k in list(session.keys()):
        if k.startswith('quiz_order_') or k.startswith('options_order_'):
            session.pop(k)
    return render_template('menu.html')

@app.route('/quiz_select', methods=['GET'])
@login_required_view
def quiz_select():
    classes = QuizClass.query.filter_by(user_id=current_user.id).all()
    class_id = request.args.get('class_id', type=int)
    topics = Topic.query.filter_by(class_id=class_id).all() if class_id else []
    return render_template('select_quiz.html', classes=classes, topics=topics, selected_class=class_id)

@app.route('/quiz', methods=['GET'])
@login_required_view
def quiz():
    db_path = os.path.join(app.instance_path, 'quiz.db')
    if not os.path.exists(db_path):
        flash('Vui lòng upload file .docx trước!')
        return redirect(url_for('menu'))
    class_id = request.args.get('class_id', type=int)
    topic_id = request.args.get('topic_id', type=int)
    if not class_id or not topic_id:
        flash('Vui lòng chọn lớp và chủ đề!')
        return redirect(url_for('menu'))
    classes = QuizClass.query.all()
    topics = Topic.query.filter_by(class_id=class_id).all()
    questions = Question.query.filter_by(topic_id=topic_id).order_by(Question.id).all()
    # Trộn thứ tự câu hỏi, lưu vào session
    quiz_order_key = f'quiz_order_{topic_id}'
    questions = get_shuffled_order(quiz_order_key, questions)

    page = int(request.args.get('page', 1))
    per_page = 7
    total_questions = len(questions)
    total_pages = (total_questions + per_page - 1) // per_page if total_questions else 1
    start = (page - 1) * per_page
    end = start + per_page
    page_questions = questions[start:end]
    quiz_data = []
    for q in page_questions:
        abcd = ['A', 'B', 'C', 'D']
        # Trộn đáp án, lưu vào session
        options_order_key = f'options_order_{q.id}'
        options = get_shuffled_order(options_order_key, q.options)
        options_dict = {opt.label: opt.text for opt in options}
        # Nếu số đáp án < 4, bổ sung text rỗng cho đủ 4 label
        for label in abcd:
            if label not in options_dict:
                options_dict[label] = ""
        correct_label = next((opt.label for opt in options if opt.is_correct), None)
        quiz_data.append({"id": q.id, "question": q.text, "options": options_dict, "correct_label": correct_label})
    
    answered_questions = session.get('answered_questions', {})
    question_results = session.get('question_results', {})  # Thêm kết quả đúng/sai
    question_ids = [q.id for q in questions]
    correct_labels = {str(q.id): qd['correct_label'] for q, qd in zip(page_questions, quiz_data)}
    
    return render_template('quiz.html',
                         questions=quiz_data,
                         page=page,
                         total_pages=total_pages,
                         question_ids=question_ids,
                         total_questions=total_questions,
                         classes=classes,
                         topics=topics,
                         selected_class=class_id,
                         selected_topic=topic_id,
                         answered_questions=answered_questions,
                         question_results=question_results,  # Truyền kết quả đúng/sai
                         correct_labels=correct_labels,
                         abcd=abcd)

@app.route('/submit', methods=['POST'])
def submit():
    db_path = os.path.join(app.instance_path, 'quiz.db')
    if not os.path.exists(db_path):
        flash('Vui lòng upload file .docx trước!')
        return redirect(url_for('menu'))
    class_id = request.args.get('class_id', type=int)
    topic_id = request.args.get('topic_id', type=int)
    page = int(request.args.get('page', 1))
    if not topic_id:
        flash('Vui lòng chọn lớp và chủ đề!')
        return redirect(url_for('menu'))

    # Lấy danh sách câu trả lời từ session
    answered = session.get('answered_questions', {})
    question_results = session.get('question_results', {})
    
    # Tính điểm dựa trên kết quả đã lưu trong session
    score = sum(1 for result in question_results.values() if result)
    
    # Lấy tổng số câu hỏi của topic
    total_questions = Question.query.filter_by(topic_id=topic_id).count()
    
    # Xóa trạng thái đã làm sau khi nộp bài
    session.pop('answered_questions', None)
    session.pop('question_results', None)
    
    # Tính điểm phần trăm
    percentage_score = (score / total_questions) * 100 if total_questions > 0 else 0
    
    # Lưu điểm vào database
    session_id = session.sid if hasattr(session, 'sid') else request.cookies.get(app.session_cookie_name)
    quiz_score = QuizScore(
        session_id=session_id,
        class_id=class_id,
        topic_id=topic_id,
        score=percentage_score
    )
    db.session.add(quiz_score)
    db.session.commit()
    
    return render_template('result.html', 
                         score=score, 
                         total=total_questions,
                         answered_count=len(answered),
                         class_id=class_id, 
                         topic_id=topic_id, 
                         page=page)

@app.route('/read_file', methods=['GET', 'POST'])
@login_required_view
def read_file():
    classes = QuizClass.query.filter_by(user_id=current_user.id).all()
    if request.method == 'POST':
        file = request.files['file']
        class_name = request.form.get('class_name')
        topic_name = request.form.get('topic_name')
        if file and file.filename.endswith('.docx') and class_name and topic_name:
            if not os.path.exists('uploads'):
                os.makedirs('uploads')
            filename = secure_filename(file.filename)
            unique_filename = f"{int(time.time())}_{filename}"
            filepath = os.path.join('uploads', unique_filename)
            file.save(filepath)
            db_path = os.path.join(app.instance_path, 'quiz.db')
            if not os.path.exists(app.instance_path):
                os.makedirs(app.instance_path)
            # Không xóa DB, chỉ thêm vào class/topic mới
            init_db_from_docx(filepath, class_name, topic_name)
            # Xóa file tạm sau khi đã nạp vào DB
            try:
                os.remove(filepath)
            except Exception:
                pass
            flash('Đã nạp file mới thành công!')
            return redirect(url_for('menu'))
        else:
            flash('Vui lòng nhập đủ thông tin và chọn file .docx!')
    return render_template('read_file.html', classes=classes)

@app.route('/edit_questions_select')
@login_required_view
def edit_questions_select():
    classes = QuizClass.query.filter_by(user_id=current_user.id).all()
    return render_template('edit_questions_select.html', classes=classes)

@app.route('/edit_questions', methods=['GET', 'POST'])
@login_required_view
def edit_questions():
    db_path = os.path.join(app.instance_path, 'quiz.db')
    if not os.path.exists(db_path):
        flash('Vui lòng upload file .docx trước!')
        return redirect(url_for('menu'))
    class_id = request.args.get('class_id', type=int)
    topic_id = request.args.get('topic_id', type=int)
    if not class_id or not topic_id:
        return redirect(url_for('edit_questions_select'))
    all_questions = Question.query.filter_by(topic_id=topic_id).order_by(Question.id).all()
    page = int(request.args.get('page', 1))
    per_page = 7
    total_questions = len(all_questions)
    total_pages = (total_questions + per_page - 1) // per_page if total_questions else 1
    start = (page - 1) * per_page
    end = start + per_page
    questions = all_questions[start:end]
    question_ids = [q.id for q in all_questions]
    if request.method == 'POST':
        for q in questions:
            new_text = request.form.get(f'q{q.id}')
            if new_text:
                q.text = new_text
            # Cập nhật đáp án và đáp án đúng
            for opt in q.options:
                opt_text = request.form.get(f'opt{opt.id}')
                is_correct = request.form.get(f'correct_{q.id}') == opt.label
                if opt_text is not None:
                    opt.text = opt_text
                opt.is_correct = is_correct
        db.session.commit()
        flash('Đã lưu thay đổi!')
        return redirect(url_for('edit_questions', class_id=class_id, topic_id=topic_id, page=page))
    return render_template('edit_questions.html', questions=questions, class_id=class_id, topic_id=topic_id, page=page, total_pages=total_pages, question_ids=question_ids, total_questions=total_questions)

@app.route('/topics')
def get_topics():
    class_id = request.args.get('class_id', type=int)
    topics = Topic.query.filter_by(class_id=class_id).all()
    return jsonify({'topics': [{'id': t.id, 'name': t.name} for t in topics]})

@app.route('/review_wrong_answers', methods=['GET'])
@login_required_view
def review_wrong_answers():
    class_id = request.args.get('class_id', type=int)
    topic_id = request.args.get('topic_id', type=int)
    
    # Lấy danh sách các câu sai theo lớp và chủ đề, không giới hạn session
    wrong_answers_query = WrongAnswer.query.filter_by(
        class_id=class_id,
        topic_id=topic_id
    )
    
    # Lấy ID câu hỏi duy nhất
    wrong_question_ids = [item.question_id for item in wrong_answers_query.distinct(WrongAnswer.question_id).all()]
    
    if not wrong_question_ids:
        flash('Không có câu trả lời sai nào để ôn tập!')
        return redirect(url_for('menu'))
    
    # Lấy thông tin chi tiết của các câu hỏi
    questions = Question.query.filter(Question.id.in_(wrong_question_ids)).all()
    
    # Xóa trạng thái làm bài cũ trước khi bắt đầu review
    session.pop('answered_questions', None)
    session.pop('question_results', None)
    session.modified = True

    quiz_data = []
    for q in questions:
        options_dict = {opt.label: opt.text for opt in q.options}
        correct_label = next((opt.label for opt in q.options if opt.is_correct), None)
        quiz_data.append({
            "id": q.id,
            "question": q.text,
            "options": options_dict,
            "correct_label": correct_label
        })

    classes = QuizClass.query.all()
    topics = Topic.query.filter_by(class_id=class_id).all() if class_id else []
    
    return render_template('review_wrong.html', 
                         questions=quiz_data,
                         classes=classes,
                         topics=topics,
                         selected_class=class_id,
                         selected_topic=topic_id,
                         abcd=['A', 'B', 'C', 'D'])

@app.route('/check_answer')
def check_answer():
    qid = request.args.get('qid', type=int)
    label = request.args.get('label')
    question = Question.query.get(qid)
    if not question:
        return jsonify({'error': 'Not found'}), 404
    correct_option = Option.query.filter_by(question_id=qid, is_correct=True).first()
    if not correct_option:
        return jsonify({'error': 'No correct answer'}), 404
    is_correct = (label == correct_option.label)
    
    # Lưu trạng thái đã trả lời và kết quả đúng/sai vào session
    if 'answered_questions' not in session:
        session['answered_questions'] = {}
    if 'question_results' not in session:
        session['question_results'] = {}
    
    session['answered_questions'][str(qid)] = label
    session['question_results'][str(qid)] = is_correct
    session.modified = True
    
    session_id = session.sid if hasattr(session, 'sid') else request.cookies.get(app.session_cookie_name)
    class_id = request.args.get('class_id', type=int)
    topic_id = request.args.get('topic_id', type=int)
    is_retry = request.args.get('is_retry')
    
    if class_id and topic_id:
        if is_correct:
            # Nếu trả lời đúng, xóa khỏi danh sách câu sai
            # Khi review, xóa tất cả các lần ghi nhận sai của câu hỏi này cho topic.
            # Khi làm quiz thường, chỉ xóa lần ghi nhận sai trong session hiện tại.
            query = WrongAnswer.query.filter_by(
                class_id=class_id,
                topic_id=topic_id,
                question_id=qid
            )
            if not is_retry:
                query = query.filter_by(session_id=session_id)
            
            query.delete()
            db.session.commit()
        else:
            # Khi làm quiz thường và trả lời sai, thêm vào DB nếu chưa có
            if not is_retry:
                existing = WrongAnswer.query.filter_by(
                    session_id=session_id,
                    class_id=class_id,
                    topic_id=topic_id,
                    question_id=qid
                ).first()
                
                if not existing:
                    wa = WrongAnswer(
                        session_id=session_id,
                        class_id=class_id,
                        topic_id=topic_id,
                        question_id=qid
                    )
                    db.session.add(wa)
                    db.session.commit()
    
    return jsonify({'correct': is_correct, 'correct_label': correct_option.label})

@app.route('/history')
def history():
    class_id = request.args.get('class_id', type=int)
    topic_id = request.args.get('topic_id', type=int)
    
    classes = QuizClass.query.all()
    topics = Topic.query.filter_by(class_id=class_id).all() if class_id else []
    
    stats = {}
    if class_id and topic_id:
        session_id = session.sid if hasattr(session, 'sid') else request.cookies.get(app.session_cookie_name)
        
        # Lấy số lần làm bài (dựa trên số lần có câu trả lời sai khác nhau)
        attempt_count = db.session.query(db.func.count(db.distinct(WrongAnswer.timestamp))).\
            filter_by(session_id=session_id, class_id=class_id, topic_id=topic_id).scalar()
        
        # Lấy danh sách câu hay sai và số lần sai
        wrong_answers = db.session.query(
            WrongAnswer.question_id,
            db.func.count(WrongAnswer.id).label('wrong_count')
        ).filter_by(
            session_id=session_id,
            class_id=class_id,
            topic_id=topic_id
        ).group_by(
            WrongAnswer.question_id
        ).order_by(
            db.desc('wrong_count')
        ).all()
        
        # Lấy thông tin chi tiết của các câu hay sai
        frequent_wrong_questions = []
        for wa in wrong_answers:
            question = Question.query.get(wa.question_id)
            if question:
                frequent_wrong_questions.append({
                    'text': question.text,
                    'wrong_count': wa.wrong_count
                })
        
        stats = {
            'attempt_count': attempt_count,
            'wrong_count': len(wrong_answers),
            'frequent_wrong_questions': frequent_wrong_questions,
            'highest_score': 85  # Tạm thời để cố định, có thể thêm bảng lưu điểm sau
        }
    
    return render_template('history.html',
                         classes=classes,
                         topics=topics,
                         selected_class=class_id,
                         selected_topic=topic_id,
                         attempt_count=stats.get('attempt_count', 0),
                         wrong_count=stats.get('wrong_count', 0),
                         frequent_wrong_questions=stats.get('frequent_wrong_questions', []),
                         highest_score=stats.get('highest_score', 0))

@app.route('/submit_review', methods=['POST'])
def submit_review():
    data = request.get_json()
    class_id = data.get('class_id')
    topic_id = data.get('topic_id')
    answers = data.get('answers', {})
    
    if not class_id or not topic_id:
        return jsonify({'success': False, 'message': 'Thiếu thông tin lớp hoặc chủ đề'})
    
    session_id = session.sid if hasattr(session, 'sid') else request.cookies.get(app.session_cookie_name)
    
    score = 0
    # Xóa các câu trả lời đúng khỏi danh sách câu sai và tính điểm
    for question_id, is_correct in answers.items():
        if is_correct:
            score += 1
            WrongAnswer.query.filter_by(
                session_id=session_id,
                class_id=class_id,
                topic_id=topic_id,
                question_id=int(question_id)
            ).delete()
    
    db.session.commit()

    total = len(answers)
    answered_count = len(answers)
    
    # Xóa trạng thái đáp án khỏi session để không ảnh hưởng lần làm bài sau
    session.pop('answered_questions', None)
    session.pop('question_results', None)

    # Lưu kết quả review vào session
    session['review_result'] = {
        'score': score,
        'total': total,
        'answered_count': answered_count
    }
    session.modified = True
    
    # Chuyển hướng về trang kết quả review
    return jsonify({
        'success': True,
        'redirect_url': url_for('review_result', class_id=class_id, topic_id=topic_id)
    })

@app.route('/review_result')
def review_result():
    class_id = request.args.get('class_id', type=int)
    topic_id = request.args.get('topic_id', type=int)

    review_result_data = session.pop('review_result', None)

    if not review_result_data:
        flash('Không tìm thấy kết quả review.')
        return redirect(url_for('menu'))
        
    return render_template('result.html',
                           score=review_result_data['score'],
                           total=review_result_data['total'],
                           answered_count=review_result_data['answered_count'],
                           class_id=class_id,
                           topic_id=topic_id)

@app.route('/get_history_stats')
def get_history_stats():
    class_id = request.args.get('class_id', type=int)
    topic_id = request.args.get('topic_id', type=int)
    
    if not class_id:
        return jsonify({
            'success': False,
            'message': 'Thiếu thông tin lớp'
        })
    
    session_id = session.sid if hasattr(session, 'sid') else request.cookies.get(app.session_cookie_name)
    
    # Nếu không có topic_id, lấy thống kê cho cả lớp
    if not topic_id:
        # Lấy số lần làm bài của lớp
        attempt_count = db.session.query(db.func.count(db.distinct(WrongAnswer.timestamp))).\
            filter_by(session_id=session_id, class_id=class_id).scalar()
        
        # Lấy tổng số câu hay sai của lớp
        wrong_count = db.session.query(db.func.count(db.distinct(WrongAnswer.question_id))).\
            filter_by(session_id=session_id, class_id=class_id).scalar()
        
        return jsonify({
            'success': True,
            'stats': {
                'attempt_count': attempt_count,
                'wrong_count': wrong_count
            }
        })
    
    # Nếu có topic_id, lấy thống kê chi tiết cho topic
    # Lấy số lần làm bài
    attempt_count = db.session.query(db.func.count(db.distinct(WrongAnswer.timestamp))).\
        filter_by(session_id=session_id, class_id=class_id, topic_id=topic_id).scalar()
    
    # Lấy danh sách câu hay sai và số lần sai
    wrong_answers = db.session.query(
        WrongAnswer.question_id,
        db.func.count(WrongAnswer.id).label('wrong_count')
    ).filter_by(
        session_id=session_id,
        class_id=class_id,
        topic_id=topic_id
    ).group_by(
        WrongAnswer.question_id
    ).order_by(
        db.desc('wrong_count')
    ).all()
    
    # Lấy thông tin chi tiết của các câu hay sai
    frequent_wrong_questions = []
    for wa in wrong_answers:
        question = Question.query.get(wa.question_id)
        if question:
            frequent_wrong_questions.append({
                'id': wa.question_id,
                'text': question.text,
                'wrong_count': wa.wrong_count
            })
    
    return jsonify({
        'success': True,
        'stats': {
            'attempt_count': attempt_count,
            'wrong_count': len(wrong_answers),
            'frequent_wrong_questions': frequent_wrong_questions,
            'highest_score': 85  # Tạm thời để cố định
        }
    })

@app.route('/quiz_stats')
@login_required_view
def quiz_stats():
    class_id = request.args.get('class_id', type=int)
    topic_id = request.args.get('topic_id', type=int)
    
    if not class_id or not topic_id:
        flash('Vui lòng chọn lớp và chủ đề!')
        return redirect(url_for('menu'))
    
    session_id = session.sid if hasattr(session, 'sid') else request.cookies.get(app.session_cookie_name)
    
    # Lấy thông tin lớp và chủ đề
    quiz_class = QuizClass.query.get(class_id)
    topic = Topic.query.get(topic_id)
    if not quiz_class or not topic:
        flash('Không tìm thấy thông tin lớp hoặc chủ đề!')
        return redirect(url_for('menu'))
    
    # Lấy số lần làm bài (tính trên toàn bộ, không theo session)
    attempt_count = db.session.query(db.func.count(db.distinct(QuizScore.timestamp))).\
        filter_by(class_id=class_id, topic_id=topic_id).scalar()
    
    # Lấy điểm cao nhất (tính trên toàn bộ, không theo session)
    highest_score = db.session.query(db.func.max(QuizScore.score)).\
        filter_by(class_id=class_id, topic_id=topic_id).scalar() or 0
    
    # Lấy danh sách câu hay sai và số lần sai (tính trên toàn bộ)
    wrong_answers = db.session.query(
        WrongAnswer.question_id,
        Question.text.label('question_text'),
        db.func.count(WrongAnswer.id).label('wrong_count')
    ).join(
        Question, Question.id == WrongAnswer.question_id
    ).filter(
        WrongAnswer.class_id == class_id,
        WrongAnswer.topic_id == topic_id
    ).group_by(
        WrongAnswer.question_id,
        Question.text
    ).order_by(
        db.desc('wrong_count')
    ).all()
    
    return render_template('quiz_stats.html',
                         class_id=class_id,
                         topic_id=topic_id,
                         class_name=quiz_class.name,
                         topic_name=topic.name,
                         attempt_count=attempt_count,
                         highest_score=round(highest_score),
                         wrong_answers=wrong_answers)

@app.route('/')
def root():
    return redirect(url_for('menu'))

def init_db():
    with app.app_context():
        # Drop all tables
        db.drop_all()
        # Create all tables
        db.create_all()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
