from django.shortcuts import render
from .models import Game, Youtube, ReviewAnalysis
import re
import json
import random
from datetime import datetime
import os
from django.conf import settings

import html
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

from bs4 import BeautifulSoup
from django.http import JsonResponse

from django.db.models import Count
from collections import Counter

def preprocess_pc_requirements(pc_requirements):
    # 키 값 변환 테이블
    key_translation = {
        "minimum": "최소",
        "recommended": "권장"
    }

    requirements_dict = {}
    for key, html_content in pc_requirements.items():
        # <li> 태그 안의 내용을 추출
        li_contents = re.findall(r'<li>(.*?)</li>', html_content, re.DOTALL)
        # 태그 제거 및 정리
        cleaned_contents = [
            re.sub(r'<.*?>', '', li).replace('<br>', '').strip()
            for li in li_contents
        ]
        # 번역된 키 값으로 저장
        translated_key = key_translation.get(key, key)  # 키 변환, 기본적으로 원래 키 사용
        requirements_dict[translated_key] = cleaned_contents
    return requirements_dict

def game_javaScript(game):
    game_data = {
        'name': game.name,
        'discount_percent': game.discount_percent,
        'initial_price': game.initial_price,
        'final_price': game.final_price,
        'header_image': game.header_image,
        'app_id': game.app_id
    }
    return JsonResponse(game_data)

def main_view(request):
    # URL 파라미터에서 카테고리를 가져옴. 기본값은 'popular'
    category = request.GET.get('category', 'popular')

    # 필터링 조건 설정
    if category == 'popular':
        json_path = os.path.join(settings.BASE_DIR, 'functions', 'top_100_games.json')
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                top_games_data = json.load(f)
        
            app_ids = [game['app_id'] for game in top_games_data]
            games = Game.objects.filter(app_id__in=app_ids)
            games_dict = {game.app_id: game for game in games}
            games = [games_dict[app_id] for app_id in app_ids if app_id in games_dict]
        except (FileNotFoundError, json.JSONDecodeError):
            games = Game.objects.all()[:100]
    elif category == 'free':
        games = Game.objects.filter(final_price=0)[:100]
    elif category == 'discounted':
        games = Game.objects.filter(discount_percent__gt=0)[:100]
    elif category == 'single':
        games = Game.objects.filter(categories__icontains={'description': '싱글 플레이어'})[:100]
    elif category == 'multi':
        games = Game.objects.filter(categories__icontains={'description': '멀티플레이어'})[:100]
    else:
        games = Game.objects.all()[:100]

    for game in games:
        game.final_price_int = int(float(str(game.final_price)))
        game.initial_price_int = int(float(str(game.initial_price)))

        review_analysis = ReviewAnalysis.objects.filter(app_id=game.app_id).first()
        if review_analysis and review_analysis.all_analysis:
            all_analysis = review_analysis.all_analysis
            total_positive = all_analysis[0]['positive']
            total_negative = all_analysis[0]['negative']
            total_reviews = total_positive + total_negative
            
            if total_reviews > 10:
                positive_ratio = int(total_positive / total_reviews * 100)
            else:
                positive_ratio = 0
        else:
            positive_ratio = 0
        game.positive_ratio = positive_ratio
        # if positive_ratio == 0:
        #     game.green_ratio = 0
        #     game.yellow_ratio = 0
        #     game.red_ratio = 0
        # else:
        #     game.green_ratio = positive_ratio
        #     game.yellow_ratio = max(0, min(positive_ratio - 40, 30))
        #     game.red_ratio = max(0, 100 - game.green_ratio - game.yellow_ratio)

        game.green_ratio = positive_ratio

        game.red_ratio = 100 - positive_ratio

    return render(request, "main.html", {'games': games})

def search_view(request):
    query = request.GET.get('search', '')
    sort_order = request.GET.get('sort', '')
    number_of_players = request.GET.get('players', '')
    price_range = request.GET.get('price', '')
    release_status = request.GET.get('status', None)
    select_tags = request.GET.get('tags', '')
    page = request.GET.get('page', 1)

    # 필요한 필드만 가져오기
    games = Game.objects.all().only(
        'name', 'final_price', 'initial_price', 'release_date', 'coming_soon', 
        'categories', 'tags', 'screenshots', 'discount_percent', 'capsule_image', 'app_id'
    )

    # 이름 검색 필터
    if query:
        games = games.filter(name__icontains=query)

    # 정렬 조건
    sort_mappings = {
        'price_desc': '-final_price',
        'price_asc': 'final_price',
        'discount_desc': '-discount_percent',
        'discount_asc': 'discount_percent',
        'release_desc': '-release_date',
        'release_asc': 'release_date',
    }
    if sort_order in sort_mappings:
        games = games.order_by(sort_mappings[sort_order])

    # 태그 필터
    if select_tags:
        games = games.filter(tags__icontains=select_tags)

    # 모든 게임을 메모리로 가져오기 (이 시점에서 QuerySet 실행)
    games_list = list(games)
    
    # 출시 상태 필터
    if release_status == 'released':
        games_list = [game for game in games_list if not game.coming_soon]
    elif release_status == 'upcoming':
        games_list = [game for game in games_list if game.coming_soon]

    # 플레이어 조건 필터 (Python에서 필터링)
    if number_of_players:
        player_category_mappings = {
            'single_player': 2,
            'multi_player': 1,
            'online_coop': 38,
        }
        if number_of_players in player_category_mappings:
            category_id = player_category_mappings[number_of_players]
            games_list = [game for game in games_list if any(category['id'] == category_id for category in game.categories)]

    # 가격 범위 필터 (Python에서 필터링)
    if price_range:
        price_ranges = {
            '_3': (0, 30000),
            '3_5': (30000, 50000),
            '5_7': (50000, 70000),
            '7_10': (70000, 100000),
            '10_': (100000, None),
        }
        if price_range in price_ranges:
            min_price, max_price = price_ranges[price_range]
            min_price = float(min_price) if min_price is not None else 0
            max_price = float(max_price) if max_price is not None else float('inf')
            games_list = [game for game in games_list if min_price <= game.final_price < max_price]

    processed_games = []
    for game in games_list:
        game_dict = {
            'name': game.name,
            'app_id': game.app_id,
            'final_price_int': int(float(str(game.final_price))),
            'initial_price_int': int(float(str(game.initial_price))),
            'discount_percent': game.discount_percent,
            'screenshots_path': [screenshot['path_thumbnail'] for screenshot in game.screenshots],
            'tags3': ', '.join(game.tags[:3]) if game.tags else [],
            'capsule_image': game.capsule_image,
            'categories': game.categories,
            'release_date': game.release_date,
            'total_reviews': 0,
            'total_positive': 0,
            'total_negative': 0,
            'positive_ratio': 0,
            'positive_keywords': '',
            'negative_keywords': ''
        }
        processed_games.append(game_dict)

    paginator = Paginator(processed_games, 20)
    try:
        paginated_games = paginator.page(page)
    except PageNotAnInteger:
        paginated_games = paginator.page(1)
    except EmptyPage:
        paginated_games = paginator.page(paginator.num_pages)

    current_page_game_ids = [game['app_id'] for game in paginated_games.object_list]

    review_analyses = {
        ra.app_id: ra 
        for ra in ReviewAnalysis.objects.filter(app_id__in=current_page_game_ids).only('app_id', 'all_analysis')
    }

    for game in paginated_games.object_list:
        review_analysis = review_analyses.get(game['app_id'])
        if review_analysis and review_analysis.all_analysis:
            all_analysis = review_analysis.all_analysis
            total_positive = all_analysis[0]['positive']
            total_negative = all_analysis[0]['negative']
            total_reviews = total_positive + total_negative
            
            game.update({
                'total_reviews': total_reviews,
                'total_positive': total_positive,
                'total_negative': total_negative,
                'positive_ratio': int(total_positive / total_reviews * 100) if total_reviews > 10 else 0,
                'positive_keywords': ', '.join([list(kw.keys())[0] for kw in all_analysis[0]['positive_keywords'][:5]]),
                'negative_keywords': ', '.join([list(kw.keys())[0] for kw in all_analysis[0]['negative_keywords'][:5]])
            })

    # AJAX 요청 처리
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        games_data = [
            {
                'id': game.id,
                'name': game.name,
                'final_price': game.final_price,
                'initial_price': game.initial_price,
                'discount_percent': game.discount_percent,
                'release_date': game.release_date,
                'coming_soon': game.coming_soon,
                'categories': game.categories,
                'tags': game.tags,
                'screenshots': [screenshot['path_thumbnail'] for screenshot in game.screenshots],
                'capsule_image': game.capsule_image,
                'total_reviews': game.total_reviews,
                'total_positive': game.total_positive,
                'total_negative': game.total_negative,
                'positive_ratio': game.positive_ratio,
                'positive_keywords': game.positive_keywords,
                'negative_keywords': game.negative_keywords,
            }
            for game in paginated_games
        ]
        return JsonResponse({
            'games': games_data,
            'total_pages': paginator.num_pages,
            'current_page': paginated_games.number,
            'has_previous': paginated_games.has_previous(),
            'has_next': paginated_games.has_next(),
        })

    # 일반 요청 처리
    context = {
        'games': paginated_games,
        'search_query': query,
        'sort_order': sort_order,
        'release_status': release_status,
        'number_of_players': number_of_players,
        'select_tags': request.GET.get('tags', ''),
        'price_range': price_range,
        'start_page': (paginated_games.number - 1) // 10 * 10 + 1,
        'end_page': min(((paginated_games.number - 1) // 10 + 1) * 10, paginator.num_pages),
    }
    return render(request, "search.html", context)

def dashboard_view(request, app_id):
    game = Game.objects.get(app_id=app_id)
    game.final_price_int = int(float(str(game.final_price)))
    game.initial_price_int = int(float(str(game.initial_price)))
    game.short_description = html.unescape(game.short_description)
    game.pc_requirements = preprocess_pc_requirements(game.pc_requirements)

    game_json = game_javaScript(game)

    review_analysis = ReviewAnalysis.objects.filter(app_id=app_id).first()
    if review_analysis and review_analysis.all_analysis:
        period_analysis = review_analysis.period_analysis
        all_analysis = review_analysis.all_analysis

        total_positive = all_analysis[0]['positive']
        total_negative = all_analysis[0]['negative']

        positive_keywords = []
        negative_keywords = []

        for keyword_dict in all_analysis[0]['positive_keywords']:
            for keyword, count in keyword_dict.items():
                positive_keywords.append((keyword, count))

        for keyword_dict in all_analysis[0]['negative_keywords']:
            for keyword, count in keyword_dict.items():
                negative_keywords.append((keyword, count))

        positive_keywords = sorted(positive_keywords, key=lambda x: x[1], reverse=True)
        negative_keywords = sorted(negative_keywords, key=lambda x: x[1], reverse=True)

        total_reviews = total_positive + total_negative
        if total_reviews > 10:
            positive_ratio = int(total_positive / total_reviews * 100)
        else:
            positive_ratio = 0
    else:
        period_analysis = []
        all_analysis = []
        positive_keywords = []
        negative_keywords = []
        positive_ratio = 0

    youtubes = Youtube.objects.filter(game=game.app_id)
    for youtube in youtubes:
        youtube.title = html.unescape(youtube.title)
        youtube.publishedAt = datetime.strptime(youtube.publishedAt, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y년 %m월 %d일")

    if isinstance(game.tags, str):
        game.tags = [tag.strip() for tag in game.tags.split(',')]

    if isinstance(game.supported_languages, str):
        clean_text = re.sub('<[^<]+?>', '', game.supported_languages)
        main_languages = clean_text.split('음성이 지원되는 언어')[0]
        languages = [lang.strip() for lang in main_languages.split(',')]
        game.supported_languages = [lang.replace('*', '').strip() for lang in languages]

    if isinstance(game.developers, str):
        game.developers = [dev.strip() for dev in game.developers.split(',')]

    if isinstance(game.publishers, str):
        game.publishers = [pub.strip() for pub in game.publishers.split(',')]

    recommendations = game.recommendations

    first_game = None
    random_games = []
    
    if recommendations:
        first_id = recommendations[0]['app_id']
        first_game = Game.objects.get(app_id=first_id)
        first_game.final_price_int = int(float(str(first_game.final_price)))
        first_game.initial_price_int = int(float(str(first_game.initial_price)))

        first_game_review = ReviewAnalysis.objects.filter(app_id=first_id).first()
        if first_game_review and first_game_review.all_analysis:
            total_positive_first_game = first_game_review.all_analysis[0]['positive']
            total_negative_first_game = first_game_review.all_analysis[0]['negative']
        else:
            total_positive_first_game = 0
            total_negative_first_game = 0

        total_reviews_first_game = total_positive_first_game + total_negative_first_game
        if total_reviews_first_game > 10:
            positive_ratio_first_game = int(total_positive_first_game / total_reviews_first_game * 100)
        else:
            positive_ratio_first_game = 0

        first_game.positive_ratio = positive_ratio_first_game

        if len(recommendations) > 1:
            remain_ids = [rec['app_id'] for rec in recommendations[1:]]
            random_ids = random.sample(remain_ids, min(2, len(remain_ids)))
            random_games = [Game.objects.get(app_id=rec_id) for rec_id in random_ids]

            for random_game in random_games:
                random_game.final_price_int = int(float(str(random_game.final_price)))
                random_game.initial_price_int = int(float(str(random_game.initial_price)))

                random_game_review = ReviewAnalysis.objects.filter(app_id=random_game.app_id).first()
                if random_game_review and random_game_review.all_analysis:
                    total_positive_random = random_game_review.all_analysis[0]['positive']
                    total_negative_random = random_game_review.all_analysis[0]['negative']
                else:
                    total_positive_random = 0
                    total_negative_random = 0
                total_reviews_random = total_positive_random + total_negative_random
                if total_reviews_random > 10:
                    positive_ratio_random = int(total_positive_random / total_reviews_random * 100)
                else:
                    positive_ratio_random = 0

                random_game.positive_ratio = positive_ratio_random

    years = set()
    period_data = {}

    for item in period_analysis:
        date_str = item['period'].split('~')[0]
        date = datetime.strptime(date_str, '%Y-%m-%d')
        year = date.year
        month = date.month

        if year not in period_data:
            period_data[year] = {}

        years.add(year)
        period_data[year][month] = {
            'positive': item['positive'],
            'negative': item['negative'],
            'positive_keywords': item['positive_keywords'],
            'negative_keywords': item['negative_keywords']
        }

    years = sorted(period_data.keys())
    current_year = datetime.now().year
    
    if current_year not in period_data:
        current_year = max(years) if years else current_year
    
    context = {
        'game': game,
        'first_recommendation': first_game,
        'random_recommendations': random_games,
        'youtubes': youtubes,
        'all_analysis': all_analysis,
        'positive_ratio': positive_ratio,
        'positive_keywords' : positive_keywords,
        'negative_keywords' : negative_keywords,
        'period_data': json.dumps(period_data),
        'years': years,
        'current_year': current_year,
        'game_json': game_json.content.decode('utf-8')  # JSON 문자열로 context에 추가
    }

    return render(request, 'dashboard.html', context)

def tags_view(request):
    # URL 파라미터에서 tag_name을 가져옵니다. 기본값은 'Singleplayer'
    tag_name = request.GET.get('tag', 'Singleplayer')

    # 모든 게임의 tags 필드를 가져옴
    all_tags = Game.objects.values_list('tags', flat=True)

    # 리스트 형식으로 저장된 태그를 분리
    tag_counter = Counter()
    for tag_list in all_tags:
        if tag_list:  # 빈 리스트 제외
            # 문자열로 저장된 리스트를 개별 태그로 분리
            for tag in tag_list:
                tag = tag.strip()  # 앞뒤 공백 제거
                if tag:  # 빈 문자열 제외
                    tag_counter[tag] += 1

    # 태그별 등장 횟수를 기준으로 정렬 후 상위 50개 선택
    top_tags = [tag for tag, _ in tag_counter.most_common(50)]

    games = Game.objects.filter(tags__icontains=tag_name).only(
        'name', 'final_price', 'initial_price', 'header_image', 'app_id', 'discount_percent'
    ).order_by('name')

    processed_games = []
    for game in games:
        game_dict = {
            'name': game.name,
            'header_image': game.header_image,
            'app_id': game.app_id,
            'discount_percent': game.discount_percent,
            'final_price_int': int(float(str(game.final_price))) if game.final_price else 0,
            'initial_price_int': int(float(str(game.initial_price))) if game.initial_price else 0
        }
        processed_games.append(game_dict)

    # Paginator로 페이지네이션 (9개씩)
    paginator = Paginator(processed_games, 9)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # 템플릿에 전달할 컨텍스트
    context = {
        'tags': top_tags,  # 동적으로 가져온 태그 리스트
        'selected_tag': tag_name,
        'page_obj': page_obj,
    }

    return render(request, 'tags.html', context)

