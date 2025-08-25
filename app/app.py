import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import secrets
import hashlib
from PIL import Image
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import base64

app = Flask(__name__)
app.config['SECRET_KEY'] = 'SLek3*&#(s832978@)*53'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///movies.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'app/static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Allowed file extensions for profile pictures
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Encryption payment
def decrypt_price(encrypted_price: str) -> float:
    key = 'CinemaMaxSecretKey123'  # Must match JS key
    try:
        # Decode from Base64
        decoded = base64.b64decode(encrypted_price).decode('latin1')  # keep all byte values
        
        # XOR decryption
        result = ''
        for i, char in enumerate(decoded):
            result += chr(ord(char) ^ ord(key[i % len(key)]))
        
        # Convert to float
        return float(result)
    except Exception as e:
        # Raise a clear error if decryption fails
        raise ValueError(f"Invalid encrypted price: {encrypted_price}") from e

# --- Decrypt Seats ---
def decrypt_seats(encrypted_seats: str) -> list:
    key = 'CinemaMaxSecretKey123'  # Must match JS key
    try:
        decoded = base64.b64decode(encrypted_seats).decode('latin1')
        result = ''
        for i, char in enumerate(decoded):
            result += chr(ord(char) ^ ord(key[i % len(key)]))
        # Return as list of seat IDs
        return result.split(',') if result else []
    except Exception as e:
        raise ValueError(f"Invalid encrypted seats: {encrypted_seats}") from e

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    profile_picture = db.Column(db.String(200), default='default.svg')
    wallet_balance = db.Column(db.Float, default=200.0)  # Default $200 wallet balance
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    bookings = db.relationship('Booking', backref='user', lazy=True)
    reviews = db.relationship('Review', backref='user', lazy=True)
    watchlist = db.relationship('Watchlist', backref='user', lazy=True)

class Movie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    genre = db.Column(db.String(100))
    rating = db.Column(db.String(10))
    duration = db.Column(db.Integer)  # in minutes
    poster_url = db.Column(db.String(500))
    trailer_url = db.Column(db.String(500))
    cast = db.Column(db.Text)
    director = db.Column(db.String(200))
    release_date = db.Column(db.Date)
    is_now_showing = db.Column(db.Boolean, default=True)
    price = db.Column(db.Float, default=12.99)
    
    reviews = db.relationship('Review', backref='movie', lazy=True)
    showtimes = db.relationship('Showtime', backref='movie', lazy=True)

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    rating = db.Column(db.Integer)  # 1-5 stars
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Cinema(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    total_seats = db.Column(db.Integer, default=50)
    
    showtimes = db.relationship('Showtime', backref='cinema', lazy=True)

class Showtime(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    cinema_id = db.Column(db.Integer, db.ForeignKey('cinema.id'), nullable=False)
    show_date = db.Column(db.Date, nullable=False)
    show_time = db.Column(db.Time, nullable=False)
    available_seats = db.Column(db.Integer, default=50)

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    seats = db.Column(db.String(200))  # JSON string of seat numbers
    total_price = db.Column(db.Float)
    booking_date = db.Column(db.DateTime, default=datetime.utcnow)
    qr_code = db.Column(db.String(100))
    ticket_hash = db.Column(db.String(64), unique=True)  # SHA-256 hash for public sharing
    payment_method = db.Column(db.String(50), default='wallet')  # Track payment method
    
    showtime = db.relationship('Showtime', backref='bookings')

class Watchlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    added_date = db.Column(db.DateTime, default=datetime.utcnow)
    
    movie = db.relationship('Movie')

def generate_ticket_hash(booking_id: int) -> str:
    """Generate a stable SHA-256 hash from the booking ID"""
    return hashlib.sha256(str(booking_id).encode()).hexdigest()


def get_ticket_display_id(booking_id: int) -> str:
    """Generate a short uppercase hash from the booking ID"""
    return hashlib.sha256(str(booking_id).encode()).hexdigest()[:12].upper()


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route('/')
def home():
    search = request.args.get('search', '')
    genre_filter = request.args.get('genre', '')
    
    query = Movie.query
    
    if search:
        query = query.filter(Movie.title.contains(search) | Movie.cast.contains(search))
    
    if genre_filter:
        query = query.filter(Movie.genre.contains(genre_filter))
    
    now_showing = query.filter(Movie.is_now_showing == True).all()
    coming_soon = Movie.query.filter(Movie.is_now_showing == False).all()
    
    genres = db.session.query(Movie.genre).distinct().all()
    genres = [g[0] for g in genres if g[0]]
    
    return render_template('home.html', now_showing=now_showing, 
                         coming_soon=coming_soon, genres=genres,
                         search=search, genre_filter=genre_filter)

@app.route('/movie/<int:id>')
def movie_detail(id):
    movie = Movie.query.get_or_404(id)
    reviews = Review.query.filter_by(movie_id=id).order_by(Review.created_at.desc()).all()
    showtimes = Showtime.query.filter_by(movie_id=id).all()
    
    is_in_watchlist = False
    if current_user.is_authenticated:
        is_in_watchlist = Watchlist.query.filter_by(user_id=current_user.id, movie_id=id).first() is not None
    
    return render_template('movie_detail.html', movie=movie, reviews=reviews,
                         showtimes=showtimes, is_in_watchlist=is_in_watchlist)


@app.route('/movie/<int:id>/reviews', methods=['GET', 'POST'])
@login_required
def movie_reviews(id):
    movie = Movie.query.get_or_404(id)
    
    if request.method == 'POST':
        content = request.form.get('content')
        rating = request.form.get('rating')

        if content and rating:
            # manually sanitize <, >, and '
            content = content.replace("<", "&lt;") \
                             .replace(">", "&gt;") \
                             .replace("(", "") \
                             .replace(")", "") \
                             .replace("\"", "&quot;")
            
            review = Review(
                user_id=current_user.id,
                movie_id=id,
                content=content,
                rating=int(rating)
            )
            db.session.add(review)
            db.session.commit()
            flash('Review added successfully!', 'success')
        
        return redirect(url_for('movie_reviews', id=id))
    
    reviews = Review.query.filter_by(movie_id=id).order_by(Review.created_at.desc()).all()
    return render_template('reviews.html', movie=movie, reviews=reviews)



@app.route('/movie/<int:id>/book')
@login_required
def book_movie(id):
    movie = Movie.query.get_or_404(id)
    cinemas = Cinema.query.all()
    showtimes = Showtime.query.filter_by(movie_id=id).all()
    
    return render_template('booking.html', movie=movie, cinemas=cinemas, showtimes=showtimes)

@app.route('/payment', methods=['GET', 'POST'])
@login_required
def payment():
    if request.method == 'POST':
        showtime_id = request.form.get('showtime_id')
        encrypted_seats = request.form.get('seats')
        encrypted_price = request.form.get('total_price')

        try:
            # Decrypt seats as comma-separated string
            seats = ','.join(decrypt_seats(encrypted_seats))  # ensures "A1,C2"
            print(seats)
            total_price = float(decrypt_price(encrypted_price))
            print(total_price)
        except Exception:
            flash('Invalid payment data. Cannot process payment.', 'error')
            return redirect(url_for('book_movie', id=showtime_id))

        # Check wallet balance
        if current_user.wallet_balance < total_price:
            flash(f'Insufficient wallet balance. You need ${total_price:.2f} but only have ${current_user.wallet_balance:.2f}', 'error')
            return redirect(url_for('book_movie', id=showtime_id))

        # Deduct wallet and create booking
        current_user.wallet_balance -= total_price
        qr_code = secrets.token_urlsafe(16)

        booking = Booking(
            user_id=current_user.id,
            showtime_id=int(showtime_id),
            seats=seats,  # store as comma-separated string
            total_price=total_price,
            qr_code=qr_code,
            payment_method='wallet'
        )

        db.session.add(booking)
        db.session.flush()  # get booking ID
        booking.ticket_hash = generate_ticket_hash(booking.id)

        # Update available seats
        showtime = Showtime.query.get(showtime_id)
        seat_count = len(seats.split(',')) if seats else 1
        showtime.available_seats -= seat_count

        db.session.commit()
        flash(f'Payment successful! ${total_price:.2f} deducted from your wallet. Your booking is confirmed.', 'success')
        return redirect(url_for('dashboard'))

    # GET: show payment page
    showtime_id = request.args.get('showtime_id')
    encrypted_seats = request.args.get('seats')
    encrypted_price = request.args.get('total_price', '0')

    try:
        # Decrypt for display
        seats = decrypt_seats(encrypted_seats) if encrypted_seats else ''  # still "A1,C2,V4"
        total_price_display = float(decrypt_price(encrypted_price)) if encrypted_price else 0.0
    except Exception:
        flash('Invalid payment data. Cannot process payment.', 'error')
        return redirect(url_for('book_movie', id=showtime_id))

    showtime = Showtime.query.get(showtime_id)

    return render_template(
        'payment.html',
        showtime=showtime,
        seats=seats,                        # string for UI display
        total_price_display=total_price_display,
        total_price_encrypted=encrypted_price,
        seats_encrypted=encrypted_seats
    )



@app.route('/dashboard')
@login_required
def dashboard():
    bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.booking_date.desc()).all()
    watchlist = Watchlist.query.filter_by(user_id=current_user.id).all()
    
    return render_template('dashboard.html', bookings=bookings, watchlist=watchlist)

@app.route('/watchlist/add/<int:movie_id>')
@login_required
def add_to_watchlist(movie_id):
    existing = Watchlist.query.filter_by(user_id=current_user.id, movie_id=movie_id).first()
    
    if not existing:
        watchlist_item = Watchlist(user_id=current_user.id, movie_id=movie_id)
        db.session.add(watchlist_item)
        db.session.commit()
        flash('Movie added to watchlist!', 'success')
    else:
        flash('Movie already in watchlist!', 'info')
    
    return redirect(url_for('movie_detail', id=movie_id))

@app.route('/watchlist/remove/<int:movie_id>')
@login_required
def remove_from_watchlist(movie_id):
    watchlist_item = Watchlist.query.filter_by(user_id=current_user.id, movie_id=movie_id).first()
    
    if watchlist_item:
        db.session.delete(watchlist_item)
        db.session.commit()
        flash('Movie removed from watchlist!', 'success')
    
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('home'))
    
    movies = Movie.query.all()
    users = User.query.all()
    bookings = Booking.query.all()
    
    return render_template('admin.html', movies=movies, users=users, bookings=bookings)

@app.route('/admin/movie/add', methods=['GET', 'POST'])
@login_required
def add_movie():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        movie = Movie(
            title=request.form['title'],
            description=request.form['description'],
            genre=request.form['genre'],
            rating=request.form['rating'],
            duration=int(request.form['duration']),
            poster_url=request.form['poster_url'],
            trailer_url=request.form['trailer_url'],
            cast=request.form['cast'],
            director=request.form['director'],
            release_date=datetime.strptime(request.form['release_date'], '%Y-%m-%d').date(),
            is_now_showing=bool(request.form.get('is_now_showing')),
            price=float(request.form['price'])
        )
        
        db.session.add(movie)
        db.session.commit()
        flash('Movie added successfully!', 'success')
        return redirect(url_for('admin_panel'))
    
    return render_template('add_movie.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid email or password.', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(username=username).first():
            flash('Username already taken.', 'error')
            return render_template('register.html')
        
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            wallet_balance=200.0  # Default wallet balance
        )
        
        db.session.add(user)
        db.session.commit()
        
        login_user(user)
        flash('Registration successful! Welcome to CinemaMax! You have $200 in your wallet.', 'success')
        return redirect(url_for('home'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('home'))

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        flash('Thank you for your message! We\'ll get back to you soon.', 'success')
        return redirect(url_for('contact'))
    
    return render_template('contact.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def update_profile():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        # Validate username and email
        if not username or not email:
            flash('Username and email are required.', 'error')
            return render_template('profile.html')
        
        # Check if username is taken by another user
        existing_user = User.query.filter(User.username == username, User.id != current_user.id).first()
        if existing_user:
            flash('Username is already taken.', 'error')
            return render_template('profile.html')
        
        # Check if email is taken by another user
        existing_email = User.query.filter(User.email == email, User.id != current_user.id).first()
        if existing_email:
            flash('Email is already registered.', 'error')
            return render_template('profile.html')
        
        # Update basic information
        current_user.username = username
        current_user.email = email
        
        # Handle password change
        if current_password or new_password or confirm_password:
            if not current_password:
                flash('Current password is required to change password.', 'error')
                return render_template('profile.html')
            
            if not check_password_hash(current_user.password_hash, current_password):
                flash('Current password is incorrect.', 'error')
                return render_template('profile.html')
            
            if not new_password:
                flash('New password is required.', 'error')
                return render_template('profile.html')
            
            if len(new_password) < 8:
                flash('New password must be at least 8 characters long.', 'error')
                return render_template('profile.html')
            
            if new_password != confirm_password:
                flash('New passwords do not match.', 'error')
                return render_template('profile.html')
            
            # Update password
            current_user.password_hash = generate_password_hash(new_password)
            flash('Password updated successfully!', 'success')
        
        try:
            db.session.commit()
            flash('Profile updated successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while updating your profile.', 'error')
        
        return redirect(url_for('update_profile'))
    
    return render_template('profile.html')

@app.route('/ticket/<ticket_hash>')
def ticket_details(ticket_hash):
    # Try to find booking by ticket hash (for public sharing)
    booking = Booking.query.filter_by(ticket_hash=ticket_hash).first()
    
    if not booking:
        flash('Ticket not found. Please check the link and try again.', 'error')
        return redirect(url_for('home'))
    
    # If user is authenticated and it's not their ticket, show warning but allow viewing
    is_owner = current_user.is_authenticated and booking.user_id == current_user.id
    
    return render_template('ticket_details.html', booking=booking, is_owner=is_owner)

@app.route('/my-ticket/<int:booking_id>')
@login_required
def my_ticket_details(booking_id):
    """Private route for users to access their own tickets"""
    booking = Booking.query.get_or_404(booking_id)
    
    # Ensure user can only view their own tickets
    if booking.user_id != current_user.id:
        flash('Access denied. You can only view your own tickets.', 'error')
        return redirect(url_for('dashboard'))
    
    # Redirect to public ticket URL
    return redirect(url_for('ticket_details', ticket_hash=booking.ticket_hash))

@app.route('/update_profile_picture', methods=['POST'])
@login_required
def update_profile_picture():
    if 'profile_picture' not in request.files:
        return jsonify({'success': False, 'error': 'No file selected'})
    
    file = request.files['profile_picture']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'})
    
    if file and allowed_file(file.filename):
        # Generate unique filename
        filename = secure_filename(f"profile_{current_user.id}_{secrets.token_hex(8)}.jpg")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        try:
            # Open and resize image
            image = Image.open(file)
            
            # Convert to RGB if necessary
            if image.mode in ('RGBA', 'LA', 'P'):
                image = image.convert('RGB')
            
            # Resize to 300x300 and crop to square
            size = min(image.size)
            left = (image.width - size) // 2
            top = (image.height - size) // 2
            right = left + size
            bottom = top + size
            
            image = image.crop((left, top, right, bottom))
            image = image.resize((300, 300), Image.Resampling.LANCZOS)
            
            # Save the image
            image.save(filepath, 'JPEG', quality=85)
            
            # Delete old profile picture if it's not the default
            if current_user.profile_picture != 'default.svg':
                old_filepath = os.path.join(app.config['UPLOAD_FOLDER'], current_user.profile_picture)
                if os.path.exists(old_filepath):
                    os.remove(old_filepath)
            
            # Update user's profile picture in database
            current_user.profile_picture = filename
            db.session.commit()
            
            return jsonify({'success': True, 'filename': filename})
            
        except Exception as e:
            return jsonify({'success': False, 'error': f'Error processing image: {str(e)}'})
    
    return jsonify({'success': False, 'error': 'Invalid file type'})

@app.route('/wallet')
@login_required
def wallet():
    """Display wallet balance and transaction history"""
    return render_template('wallet.html')

@app.route('/wallet/add', methods=['POST'])
@login_required
def add_wallet_balance():
    """Add balance to wallet (admin only or for demo purposes)"""
    if not current_user.is_admin:
        flash('Access denied. Only admins can add wallet balance.', 'error')
        return redirect(url_for('wallet'))
    
    amount = float(request.form.get('amount', 0))
    if amount > 0:
        current_user.wallet_balance += amount
        db.session.commit()
        flash(f'${amount:.2f} added to your wallet!', 'success')
    else:
        flash('Invalid amount.', 'error')
    
    return redirect(url_for('wallet'))

def create_sample_data():
    # Create admin user
    admin = User.query.filter_by(email='admin@movies.com').first()
    if not admin:
        admin = User(
            username='admin',
            email='admin@movies.com',
            password_hash=generate_password_hash('admin123'),
            is_admin=True,
            wallet_balance=1000.0  # Admin gets more wallet balance
        )
        db.session.add(admin)
    
    # Create sample cinema
    cinema = Cinema.query.first()
    if not cinema:
        cinema = Cinema(name='CinemaMax', location='The View')
        cinema2 = Cinema(name='CinemaMax', location='Nakheel Mall')
        db.session.add(cinema)
        db.session.add(cinema2)
        db.session.commit()  # commit so cinema.id is available
    
    # Create sample movies
    if Movie.query.count() == 0:
        movies = [
            Movie(
                title='Mr. Robot',
                description='A cybersecurity engineer and hacker with dissociative identity disorder becomes involved in a complex hack against a powerful corporation, challenging his perception of reality.',
                genre='Crime, Drama, Thriller',
                rating='TV-MA',
                duration=60,
                poster_url='https://encrypted-tbn1.gstatic.com/images?q=tbn:ANd9GcSf_MjEvmd6I3x-7jgnvol3MrQmAUTBmN9vzw0BBanuFTY022jS7CHFYGldNPo0lCcUjsWetA',
                trailer_url='https://www.youtube.com/embed/xIBiJ_SzJTA',
                cast='Rami Malek, Christian Slater, Carly Chaikin',
                director='Sam Esmail',
                release_date=datetime(2015, 6, 24).date(),
                is_now_showing=True,
                price=9.99
            ),
            Movie(
                title='The Dark Knight',
                description='When the menace known as the Joker emerges, Batman must confront one of the greatest psychological and physical tests.',
                genre='Action, Crime, Drama',
                rating='PG-13',
                duration=152,
                poster_url='https://encrypted-tbn3.gstatic.com/images?q=tbn:ANd9GcTfE_qrYMBZ_JB8om-34WGaZARhpX26yWRttqIDvn4_7l--UzX8mxKcPrc59IcvTpEA_G8gPA',
                trailer_url='https://www.youtube.com/embed/EXeTwQWrcwY',
                cast='Christian Bale, Heath Ledger, Aaron Eckhart',
                director='Christopher Nolan',
                release_date=datetime(2008, 7, 18).date(),
                is_now_showing=True,
                price=14.99
            ),
            Movie(
                title='Inception',
                description='A thief who steals corporate secrets through dream-sharing technology is given the inverse task of planting an idea.',
                genre='Action, Sci-Fi, Thriller',
                rating='PG-13',
                duration=148,
                poster_url='https://cdn11.bigcommerce.com/s-yzgoj/images/stencil/1280x1280/products/2919271/5944675/MOVEB46211__19379.1679590452.jpg?c=2',
                trailer_url='https://www.youtube.com/embed/YoHD9XEInc0',
                cast='Leonardo DiCaprio, Marion Cotillard, Tom Hardy',
                director='Christopher Nolan',
                release_date=datetime(2010, 7, 16).date(),
                is_now_showing=True,
                price=13.99
            ),
            Movie(
                title='Interstellar',
                description='A team of explorers travel through a wormhole in space in an attempt to ensure humanity\'s survival.',
                genre='Adventure, Drama, Sci-Fi',
                rating='PG-13',
                duration=169,
                poster_url='https://i.ebayimg.com/images/g/zu4AAOSw2spbJQ0J/s-l1200.jpg',
                trailer_url='https://www.youtube.com/embed/zSWdZVtXT7E',
                cast='Matthew McConaughey, Anne Hathaway, Jessica Chastain',
                director='Christopher Nolan',
                release_date=datetime(2014, 11, 7).date(),
                is_now_showing=True,
                price=12.99
            ),
            Movie(
                title='Bad Boys for Life',
                description='Miami detectives Mike Lowrey and Marcus Burnett must face off against a mother-and-son pair of drug lords who wreak vengeance on them.',
                genre='Action, Comedy, Crime',
                rating='R',
                duration=124,
                poster_url='https://play-lh.googleusercontent.com/_BhH-H_qCDcz_71csTBRVCTACrEC_cEnsnuknO7FAroZ0ja4qwOhmJlxk1niI440sC-aXEOfxGR7wzuMiQ',
                trailer_url='https://www.youtube.com/embed/R228yPrwqTo?si=B1rrHbiYXurRM7oI',
                cast='Will Smith, Martin Lawrence, Vanessa Hudgens, Alexander Ludwig',
                director='Adil El Arbi, Bilall Fallah',
                release_date=datetime(2020, 1, 17).date(),
                is_now_showing=True,
                price=11.99
            ),
            Movie(
                title='Snowden',
                description='The story of Edward Snowden, a former NSA contractor who leaked classified information, exposing global surveillance programs.',
                genre='Biography, Drama, Thriller',
                rating='R',
                duration=134,
                poster_url='https://i.scdn.co/image/ab67616d0000b273e9cb2acab14a4d09eb6c78c6',
                trailer_url='https://www.youtube.com/embed/QlSAiI3xMh4',
                cast='Joseph Gordon-Levitt, Shailene Woodley, Melissa Leo, Zachary Quinto',
                director='Oliver Stone',
                release_date=datetime(2016, 9, 16).date(),
                is_now_showing=True,
                price=10.99
            )

        ]
        
        for movie in movies:
            db.session.add(movie)
        db.session.commit()  # commit so movies get IDs

    # Add dummy showtimes for all movies if none exist
    movies = Movie.query.all()
    for movie in movies:
        if not Showtime.query.filter_by(movie_id=movie.id).first():
            for i in range(3):  # 3 showtimes per movie
                show_date = datetime.utcnow().date() + timedelta(days=i)
                show_time = (datetime.utcnow() + timedelta(hours=18+i)).time()  # 6PM, 7PM, 8PM
                showtime = Showtime(
                    movie_id=movie.id,
                    cinema_id=cinema.id,
                    show_date=show_date,
                    show_time=show_time,
                    available_seats=cinema.total_seats
                )
                db.session.add(showtime)
    db.session.commit()

@app.route('/api/v1/admin/users', methods=['GET'])
@login_required
def find_user():
    user_id = request.args.get('id')
    if not user_id:
        return jsonify({"error": "Missing 'id' parameter"}), 400
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    # Return user details excluding password_hash
    user_data = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
        "profile_picture": user.profile_picture,
        "wallet_balance": user.wallet_balance,
        "created_at": user.created_at.isoformat()
    }
    return jsonify(user_data), 200

@app.route('/api/v1/admin/FinUser', methods=['GET'])
@login_required
def find_fake_user():
    # Ensure only admins can use this endpoint
    if not current_user.is_admin:
        return jsonify({"error": "Access denied. Admin privileges required."}), 403




def create_default_profile_picture():
    """Create a default profile picture if it doesn't exist"""
    default_path = os.path.join(app.config['UPLOAD_FOLDER'], 'default.svg')
    if not os.path.exists(default_path):
        # Create a simple default profile picture
        from PIL import Image, ImageDraw
        
        # Create a 300x300 image with a gradient background
        img = Image.new('RGB', (300, 300), color='#667eea')
        draw = ImageDraw.Draw(img)
        
        # Draw a simple user icon
        # Head circle
        draw.ellipse([100, 80, 200, 180], fill='white')
        # Body
        draw.ellipse([75, 160, 225, 280], fill='white')
        
        img.save(default_path, 'JPEG', quality=85)

def upgrade_database():
    """Add wallet_balance column to existing users if it doesn't exist"""
    try:
        # Try to access wallet_balance column
        db.session.execute(db.text('SELECT wallet_balance FROM user LIMIT 1'))
    except:
        # Column doesn't exist, add it
        db.session.execute(db.text('ALTER TABLE user ADD COLUMN wallet_balance FLOAT DEFAULT 200.0'))
        db.session.commit()
        print("Added wallet_balance column to existing users")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        upgrade_database()  # Add wallet balance to existing users
        create_default_profile_picture()
        create_sample_data()
    app.run(debug=False)
    app.run(host="0.0.0.0", port=5001)