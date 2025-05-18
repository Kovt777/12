import os
from flask import Flask, render_template_string, request, jsonify
import folium
from geopy.geocoders import Nominatim
import ssl
import certifi
from functools import lru_cache
import requests
from requests import Session
from bs4 import BeautifulSoup
from datetime import datetime

# Конфигурация приложения
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# API ключи
API_KEY = "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"
MODEL = "deepseek/deepseek-r1:free"

# SSL конфигурация
ssl_context = ssl.create_default_context(cafile=certifi.where())

# Кеширование геоданных
@lru_cache(maxsize=100)
def search_locations(query):
    geolocator = Nominatim(
        user_agent="treasure_map_app",
        ssl_context=ssl_context,
        timeout=10
    )
    try:
        locations = geolocator.geocode(query, country_codes='RU', exactly_one=False, language='ru')
        return locations if locations else []
    except Exception as e:
        print(f"Geocoding error: {e}")
        return []

def create_map(lat, lon, points=None, zoom_start=15):
    m = folium.Map(
        location=[lat, lon],
        zoom_start=zoom_start,
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri Satellite',
        control_scale=True
    )

    if points:
        for idx, point in enumerate(points, 1):
            folium.Marker(
                location=[point[0], point[1]],
                popup=f"Точка #{idx}: {point[0]:.4f}, {point[1]:.4f}",
                icon=folium.Icon(color='red', icon='treasure-sign', prefix='fa')
            ).add_to(m)
    
    folium.Circle(
        location=[lat, lon],
        radius=500,
        color='#FFA500',
        fill=True,
        fill_color='#FFA500',
        fill_opacity=0.2
    ).add_to(m)
    
    return m

def get_weather(lat, lon):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&timezone=auto"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        temp = data.get('current_weather', {}).get('temperature')
        if temp is None:
            return None
            
        descriptions = {
            (-50, -10): "❄️ Лютый холод!",
            (-10, 0): "☃️ Морозец, но копать можно",
            (0, 10): "🌬️ Прохладно",
            (10, 20): "⛅ Идеально для поиска",
            (20, 30): "☀️ Жара, но терпимо",
            (30, 50): "🔥 Адская жара!"
        }
        
        desc = next((v for (low, high), v in descriptions.items() if low <= temp < high), 
                "Погода нормальная")
        
        return {
            'temp': temp,
            'description': desc,
            'time': datetime.now().strftime("%d.%m.%Y %H:%M"),
            'windspeed': data.get('current_weather', {}).get('windspeed', 0)
        }
    except Exception as e:
        print(f"Weather API error: {e}")
        return None

def parse_clad_sites(location_name):
    sites = [
        ("http://samara-clad.ru/", "div.post-content"),
        ("https://samarafishing.ru/board/index.php?topic=40553.0", "div.post"),
        ("https://mdrussia.ru/topic/89888-samarskaja-oblast/", "div.msg")
    ]
    
    results = []
    for url, selector in sites:
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(response.text, 'lxml')
            
            for post in soup.select(selector)[:3]:
                text = ' '.join(post.get_text(separator=' ', strip=True).split())
                if location_name.lower() in text.lower():
                    results.append({
                        'source': url,
                        'text': text[:300] + '...' if len(text) > 300 else text
                    })
                    if len(results) >= 3:
                        break
        except Exception as e:
            print(f"Error parsing {url}: {e}")
    return results

def generate_ai_prompt(location_name, lat, lon, parsed_info):
    return f"""
Ты — опытный кладоискатель с 20-летним стажем. Проанализируй локацию: 
{location_name} (координаты: {lat:.4f}, {lon:.4f}).

Дай ответ в формате HTML:

1. Историческая справка:
- Какие народы здесь жили?
- Исторические события
- Потенциальные места захоронений

2. Советы по поиску (3-5 пунктов):
- Конкретные места для проверки
- На что обратить внимание
- Особенности местности

3. Данные с форумов:
{parsed_info if parsed_info else "Нет данных"}

Будь конкретен. Если данных нет — так и скажи.

Пример ответа:
<div class='advice'>
<h3>{location_name.split(',')[0]}</h3>
<ul>
<li>Ищи вдоль старых дорог</li>
<li>Проверь корни больших деревьев</li>
</ul>
</div>
"""

def get_treasure_info(lat, lon):
    try:
        geolocator = Nominatim(user_agent="treasure_app", ssl_context=ssl_context)
        location = geolocator.reverse(f"{lat}, {lon}", language='ru', exactly_one=True)
        location_name = location.address if location else "этой локации"
        
        parsed_info = parse_clad_sites(location_name.split(',')[0])
        
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": MODEL,
            "messages": [{
                "role": "user", 
                "content": generate_ai_prompt(location_name, lat, lon, parsed_info)
            }],
            "temperature": 0.7,
            "max_tokens": 1000
        }
        
        with Session() as session:
            response = session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=30
            )
            result = response.json()
            return result['choices'][0]['message']['content']
    except Exception as e:
        print(f"AI API error: {e}")
        return "<div class='error'><p>Не удалось получить информацию</p></div>"

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Карта кладоискателя</title>
    <meta charset="utf-8">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { 
            display: flex; 
            margin: 0; 
            padding: 0; 
            font-family: Georgia;
            background: #f5f5f5;
        }
        #map { 
            width: 70%; 
            height: 100vh; 
            border-right: 3px solid #8B4513;
        }
        #sidebar {
            width: 30%; 
            height: 100vh;
            background: #2E2E2E;
            color: #D2B48C;
            padding: 20px; 
            overflow-y: auto;
        }
        .search-form { margin-bottom: 20px; }
        .form-control { 
            width: 100%; 
            padding: 10px;
            margin-bottom: 10px;
            background: #3E3E3E;
            border: 1px solid #8B4513;
            color: #D2B48C;
        }
        .btn { 
            width: 100%; 
            padding: 12px;
            background: #8B4513;
            color: white;
            border: none;
            cursor: pointer;
        }
        .locations-list { margin: 20px 0; border: 1px solid #8B4513; }
        .location-item { 
            padding: 12px; 
            border-bottom: 1px solid #8B4513;
            cursor: pointer;
        }
        .weather-card, .advice-card { 
            background: #3E3E3E;
            padding: 15px;
            margin: 20px 0;
            border: 1px solid #8B4513;
        }
        .chat-container { margin-top: 20px; }
        #chat-messages { 
            height: 200px; 
            overflow-y: auto;
            padding: 10px;
            background: #3E3E3E;
            margin-bottom: 10px;
        }
        .message { 
            max-width: 80%; 
            padding: 10px;
            margin-bottom: 10px;
            border-radius: 5px;
        }
        .user-message { 
            background: #8B4513;
            margin-left: auto;
        }
        .bot-message { 
            background: #3E3E3E;
            margin-right: auto;
        }
    </style>
</head>
<body>
    <div id="map">{{ m._repr_html_()|safe }}</div>
    <div id="sidebar">
        <h1><i class="fas fa-map"></i> Карта кладоискателя</h1>
        
        <form class="search-form" method="post" action="/search_location">
            <input type="text" name="query" class="form-control" required 
                   placeholder="Введите место поиска">
            <button type="submit" class="btn">
                <i class="fas fa-search"></i> Поиск
            </button>
        </form>

        {% if locations %}
        <div class="locations-list">
            {% for location in locations %}
            <div class="location-item" onclick="selectLocation({{ location.latitude }}, {{ location.longitude }})">
                <i class="fas fa-map-marker-alt"></i> {{ location.address }}
            </div>
            {% endfor %}
        </div>
        {% endif %}

        {% if weather %}
        <div class="weather-card">
            <h3><i class="fas fa-thermometer-half"></i> Погода: {{ weather.temp }}°C</h3>
            <p>{{ weather.description }}</p>
        </div>
        {% endif %}

        {% if treasure_info %}
        <div class="advice-card">
            <h3><i class="fas fa-coins"></i> Советы</h3>
            {{ treasure_info|safe }}
        </div>
        {% endif %}

        <div class="chat-container">
            <div id="chat-messages"></div>
            <input type="text" id="chat-input" class="form-control" placeholder="Задайте вопрос">
            <button onclick="sendMessage()" class="btn">Отправить</button>
        </div>
    </div>

    <script>
        function selectLocation(lat, lon) {
            fetch('/select_location', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `lat=${lat}&lon=${lon}`
            }).then(() => window.location.href = `/center_map?lat=${lat}&lon=${lon}`);
        }

        function sendMessage() {
            const input = document.getElementById('chat-input');
            const message = input.value.trim();
            if (!message) return;
            
            const chatContainer = document.getElementById('chat-messages');
            chatContainer.innerHTML += `<div class="message user-message">${message}</div>`;
            input.value = '';
            
            fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `message=${encodeURIComponent(message)}`
            })
            .then(r => r.json())
            .then(data => chatContainer.innerHTML += `<div class="message bot-message">${data.response}</div>`);
        }
    </script>
</body>
</html>
'''

selected_points = []

@app.route('/')
def index():
    return render_template_string(
        HTML_TEMPLATE,
        m=create_map(53.1959, 50.1002, selected_points)
    )

@app.route('/search_location', methods=['POST'])
def search_location():
    query = request.form.get('query', '').strip()
    if not query:
        return render_template_string(
            HTML_TEMPLATE,
            m=create_map(53.1959, 50.1002, selected_points),
            error="Введите название места"
        )
    
    locations = search_locations(query)
    return render_template_string(
        HTML_TEMPLATE,
        m=create_map(53.1959, 50.1002, selected_points),
        locations=locations
    )

@app.route('/select_location', methods=['POST'])
def select_location():
    try:
        selected_points.append((
            float(request.form.get('lat')),
            float(request.form.get('lon'))
        ))
        return '', 200
    except:
        return '', 400

@app.route('/center_map', methods=['GET'])
def center_map():
    try:
        lat = float(request.args.get('lat'))
        lon = float(request.args.get('lon'))
        return render_template_string(
            HTML_TEMPLATE,
            m=create_map(lat, lon, selected_points),
            weather=get_weather(lat, lon),
            treasure_info=get_treasure_info(lat, lon)
        )
    except:
        return render_template_string(
            HTML_TEMPLATE,
            m=create_map(53.1959, 50.1002, selected_points),
            error="Ошибка координат"
        )

@app.route('/chat', methods=['POST'])
def chat():
    message = request.form.get('message', '').strip()
    if not message:
        return jsonify({"response": "Введите вопрос"})
    
    try:
        prompt = f"Ты опытный кладоискатель. Ответь на вопрос: {message}"
        headers = {"Authorization": f"Bearer {API_KEY}"}
        
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7
            },
            timeout=20
        )
        return jsonify({
            "response": response.json()['choices'][0]['message']['content']
        })
    except:
        return jsonify({"response": "Ошибка соединения"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))