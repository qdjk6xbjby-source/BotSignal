import requests
import xml.etree.ElementTree as ET
from datetime import datetime

def get_news():
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            events = []
            for event in root.findall('event'):
                title = event.find('title').text
                country = event.find('country').text
                date = event.find('date').text
                time = event.find('time').text
                impact = event.find('impact').text
                
                # Фильтруем только важные новости (High Impact)
                if impact == 'High':
                    events.append({
                        'title': title,
                        'country': country,
                        'date': date,
                        'time': time
                    })
            return events
    except Exception as e:
        print(f"Error fetching news: {e}")
    return []

news = get_news()
print(f"Found {len(news)} high impact events this week.")
for e in news[:5]:
    print(f"[{e['country']}] {e['title']} at {e['date']} {e['time']}")
