from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import requests
import json
import random
import hashlib
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')

# Firebase configuration
FIREBASE_URL = 'https://casino-93903-default-rtdb.firebaseio.com'

class FirebaseDB:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip('/')
    
    def get(self, path=''):
        """Get data from Firebase"""
        url = f"{self.base_url}/{path}.json"
        response = requests.get(url)
        return response.json() if response.status_code == 200 else None
    
    def post(self, path, data):
        """Post data to Firebase"""
        url = f"{self.base_url}/{path}.json"
        response = requests.post(url, json=data)
        return response.json() if response.status_code == 200 else None
    
    def put(self, path, data):
        """Put data to Firebase"""
        url = f"{self.base_url}/{path}.json"
        response = requests.put(url, json=data)
        return response.json() if response.status_code == 200 else None
    
    def patch(self, path, data):
        """Update data in Firebase"""
        url = f"{self.base_url}/{path}.json"
        response = requests.patch(url, json=data)
        return response.json() if response.status_code == 200 else None

db = FirebaseDB(FIREBASE_URL)

def hash_password(password):
    """Hash password for security"""
    return hashlib.sha256(password.encode()).hexdigest()

def create_khasino_deck():
    """Create a 40-card Khasino deck (no face cards)"""
    suits = ['spades', 'hearts', 'diamonds', 'clubs']
    values = list(range(1, 11))  # 1-10, no face cards
    deck = []
    
    for suit in suits:
        for value in values:
            deck.append({'suit': suit, 'value': value})
    
    return deck

def calculate_points(cards):
    """Calculate Khasino points from captured cards"""
    points = 0
    spades_count = sum(1 for card in cards if card['suit'] == 'spades')
    total_cards = len(cards)
    
    # Points calculation based on Khasino rules
    for card in cards:
        # Aces = 1 point each
        if card['value'] == 1:
            points += 1
        # Two of spades ("spy two") = 1 point
        elif card['value'] == 2 and card['suit'] == 'spades':
            points += 1
        # Ten of diamonds ("mummy") = 2 points
        elif card['value'] == 10 and card['suit'] == 'diamonds':
            points += 2
    
    return {
        'points': points,
        'cards_count': total_cards,
        'spades_count': spades_count
    }

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/rules')
def rules():
    return render_template('rules.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        email = data.get('email')
        
        # Check if user already exists
        users = db.get('users') or {}
        for user_id, user_data in users.items():
            if user_data.get('username') == username:
                return jsonify({'success': False, 'message': 'Username already exists'})
        
        # Create new user
        user_data = {
            'username': username,
            'password': hash_password(password),
            'email': email,
            'balance': 1000,  # Starting balance of 1000 ZAR
            'created_at': datetime.now().isoformat(),
            'total_games': 0,
            'games_won': 0,
            'total_points': 0
        }
        
        # Add user to Firebase
        result = db.post('users', user_data)
        if result:
            return jsonify({'success': True, 'message': 'Registration successful!'})
        else:
            return jsonify({'success': False, 'message': 'Registration failed'})
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        # Find user in Firebase
        users = db.get('users') or {}
        for user_id, user_data in users.items():
            if (user_data.get('username') == username and 
                user_data.get('password') == hash_password(password)):
                session['user_id'] = user_id
                session['username'] = username
                return jsonify({'success': True, 'message': 'Login successful!'})
        
        return jsonify({'success': False, 'message': 'Invalid credentials'})
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Get user data
    user_data = db.get(f'users/{session["user_id"]}')
    if not user_data:
        return redirect(url_for('logout'))
    
    # Get available games waiting for players
    active_games = db.get('games') or {}
    waiting_games = []
    
    for game_id, game_data in active_games.items():
        if (game_data.get('status') == 'waiting' and 
            len(game_data.get('players', [])) < game_data.get('max_players', 3)):
            waiting_games.append({
                'id': game_id,
                'players': len(game_data.get('players', [])),
                'max_players': game_data.get('max_players', 3),
                'bet_amount': game_data.get('bet_amount', 0)
            })
    
    return render_template('dashboard.html', user=user_data, waiting_games=waiting_games)

@app.route('/create_game', methods=['POST'])
def create_game():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})
    
    data = request.get_json()
    bet_amount = int(data.get('bet_amount', 10))
    max_players = int(data.get('max_players', 3))
    
    # Validate bet amount and user balance
    user_data = db.get(f'users/{session["user_id"]}')
    if not user_data or user_data['balance'] < bet_amount:
        return jsonify({'success': False, 'message': 'Insufficient balance'})
    
    # Create new game
    game_data = {
        'creator': session['user_id'],
        'status': 'waiting',
        'max_players': max_players,
        'bet_amount': bet_amount,
        'players': [session['user_id']],
        'created_at': datetime.now().isoformat(),
        'deck': create_khasino_deck(),
        'layout': [],
        'current_player': 0,
        'round': 1,
        'scores': {session['user_id']: {'points': 0, 'cards': [], 'captures': []}}
    }
    
    # Shuffle deck
    random.shuffle(game_data['deck'])
    
    # Add game to Firebase
    result = db.post('games', game_data)
    if result:
        game_id = result.get('name')  # Firebase returns the generated key
        return jsonify({'success': True, 'game_id': game_id})
    
    return jsonify({'success': False, 'message': 'Failed to create game'})

@app.route('/join_game/<game_id>')
def join_game(game_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Get game data
    game_data = db.get(f'games/{game_id}')
    if not game_data:
        return redirect(url_for('dashboard'))
    
    # Check if user can join
    if (session['user_id'] not in game_data.get('players', []) and 
        len(game_data.get('players', [])) >= game_data.get('max_players', 3)):
        return redirect(url_for('dashboard'))
    
    # Join game if not already in
    if session['user_id'] not in game_data.get('players', []):
        user_data = db.get(f'users/{session["user_id"]}')
        if user_data['balance'] < game_data.get('bet_amount', 0):
            return redirect(url_for('dashboard'))
        
        # Add player to game
        game_data['players'].append(session['user_id'])
        game_data['scores'][session['user_id']] = {'points': 0, 'cards': [], 'captures': []}
        
        # Start game if enough players
        if len(game_data['players']) >= 2:  # Minimum 2 players to start
            game_data['status'] = 'active'
            deal_cards(game_data)
        
        db.put(f'games/{game_id}', game_data)
    
    return render_template('game.html', game=game_data, game_id=game_id, 
                         user_id=session['user_id'])

def deal_cards(game_data):
    """Deal cards according to Khasino rules"""
    num_players = len(game_data['players'])
    deck = game_data['deck']
    
    # Reset player hands
    for player_id in game_data['players']:
        game_data['scores'][player_id]['hand'] = []
    
    # Deal cards based on number of players
    if num_players == 2:
        # 2 players: 10 cards each per round
        cards_per_player = 10
    elif num_players == 3:
        # 3 players: 13 cards each, 1 face up on table
        cards_per_player = 13
        if game_data.get('round', 1) == 1:
            game_data['layout'] = [deck.pop()]  # 1 card face up on table
    elif num_players == 4:
        # 4 players: 10 cards each
        cards_per_player = 10
    
    # Deal cards to players
    for i in range(cards_per_player):
        for player_id in game_data['players']:
            if deck:
                game_data['scores'][player_id]['hand'].append(deck.pop())

@app.route('/api/game_state/<game_id>')
def get_game_state(game_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'})
    
    game_data = db.get(f'games/{game_id}')
    if not game_data or session['user_id'] not in game_data.get('players', []):
        return jsonify({'error': 'Game not found or access denied'})
    
    # Return game state for current player
    player_hand = game_data['scores'][session['user_id']].get('hand', [])
    
    return jsonify({
        'status': game_data.get('status'),
        'players': game_data.get('players'),
        'current_player': game_data.get('current_player', 0),
        'layout': game_data.get('layout', []),
        'hand': player_hand,
        'scores': {pid: {'points': data.get('points', 0), 
                        'cards_count': len(data.get('cards', []))} 
                  for pid, data in game_data.get('scores', {}).items()},
        'round': game_data.get('round', 1),
        'is_my_turn': game_data.get('players', [])[game_data.get('current_player', 0)] == session['user_id']
    })

@app.route('/api/play_card', methods=['POST'])
def play_card():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})
    
    data = request.get_json()
    game_id = data.get('game_id')
    card_index = data.get('card_index')
    action = data.get('action', 'discard')  # capture, build, discard
    target_cards = data.get('target_cards', [])
    
    # Get game data
    game_data = db.get(f'games/{game_id}')
    if not game_data or session['user_id'] not in game_data.get('players', []):
        return jsonify({'success': False, 'message': 'Game not found'})
    
    # Check if it's player's turn
    current_player_id = game_data['players'][game_data.get('current_player', 0)]
    if current_player_id != session['user_id']:
        return jsonify({'success': False, 'message': 'Not your turn'})
    
    # Get player's hand
    player_hand = game_data['scores'][session['user_id']].get('hand', [])
    if card_index >= len(player_hand):
        return jsonify({'success': False, 'message': 'Invalid card'})
    
    # Play the card
    played_card = player_hand.pop(card_index)
    
    # Process the action
    captured_cards = []
    if action == 'capture':
        # Implement capture logic
        captured_cards = process_capture(game_data, played_card, target_cards)
        game_data['scores'][session['user_id']]['cards'].extend(captured_cards)
        game_data['scores'][session['user_id']]['captures'].append({
            'cards': captured_cards,
            'timestamp': datetime.now().isoformat()
        })
    elif action == 'build':
        # Implement build logic
        process_build(game_data, played_card, target_cards)
    else:  # discard
        game_data['layout'].append(played_card)
    
    # Move to next player
    game_data['current_player'] = (game_data['current_player'] + 1) % len(game_data['players'])
    
    # Check if round is over (all hands empty)
    round_over = all(not game_data['scores'][pid].get('hand', []) 
                    for pid in game_data['players'])
    
    if round_over:
        end_round(game_data)
    
    # Update game in Firebase
    db.put(f'games/{game_id}', game_data)
    
    return jsonify({'success': True, 'captured': len(captured_cards)})

def process_capture(game_data, played_card, target_cards):
    """Process card capture according to Khasino rules"""
    captured = []
    layout = game_data['layout']
    
    # Simple capture: match single cards
    for i, layout_card in enumerate(layout):
        if layout_card['value'] == played_card['value']:
            captured.append(layout_card)
    
    # Remove captured cards from layout
    game_data['layout'] = [card for card in layout if card not in captured]
    captured.append(played_card)  # Include the played card
    
    return captured

def process_build(game_data, played_card, target_cards):
    """Process build creation according to Khasino rules"""
    # Simple build implementation
    build_value = played_card['value'] + sum(card['value'] for card in target_cards)
    
    # Create build on layout
    build = {
        'type': 'build',
        'value': build_value,
        'cards': [played_card] + target_cards,
        'owner': session['user_id']
    }
    
    # Remove target cards from layout and add build
    for card in target_cards:
        if card in game_data['layout']:
            game_data['layout'].remove(card)
    
    game_data['layout'].append(build)

def end_round(game_data):
    """End current round and calculate scores"""
    # Last player to capture gets remaining cards
    if game_data['layout']:
        last_capturer = None  # Would need to track this
        # For now, just clear the layout
        game_data['layout'] = []
    
    # Calculate points for each player
    for player_id in game_data['players']:
        cards = game_data['scores'][player_id].get('cards', [])
        points_data = calculate_points(cards)
        game_data['scores'][player_id]['round_points'] = points_data['points']
    
    # Deal next round if deck has cards
    if len(game_data['deck']) > 0:
        game_data['round'] += 1
        deal_cards(game_data)
    else:
        # Game over, calculate final scores
        end_game(game_data)

def end_game(game_data):
    """End game and determine winner"""
    final_scores = {}
    num_players = len(game_data['players'])
    
    for player_id in game_data['players']:
        player_data = game_data['scores'][player_id]
        cards = player_data.get('cards', [])
        points_data = calculate_points(cards)
        
        total_points = points_data['points']
        
        # Award points for most cards (2 points or 1 if tied)
        # Award points for most spades (2 points or 1 if tied)
        # These would be calculated by comparing all players
        
        final_scores[player_id] = total_points
    
    # Determine winner
    winner = max(final_scores, key=final_scores.get)
    game_data['status'] = 'finished'
    game_data['winner'] = winner
    game_data['final_scores'] = final_scores
    
    # Update user stats and balances
    update_user_stats(game_data)

def update_user_stats(game_data):
    """Update user statistics and balances after game"""
    bet_amount = game_data.get('bet_amount', 0)
    total_pot = bet_amount * len(game_data['players'])
    winner_id = game_data.get('winner')
    
    for player_id in game_data['players']:
        user_data = db.get(f'users/{player_id}')
        if user_data:
            # Update stats
            user_data['total_games'] = user_data.get('total_games', 0) + 1
            user_data['total_points'] = user_data.get('total_points', 0) + game_data['scores'][player_id].get('round_points', 0)
            
            # Update balance
            user_data['balance'] -= bet_amount  # Subtract bet
            
            if player_id == winner_id:
                user_data['balance'] += total_pot  # Winner gets the pot
                user_data['games_won'] = user_data.get('games_won', 0) + 1
            
            db.put(f'users/{player_id}', user_data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)