#!/usr/bin/env python3

import pandas as pd
import requests
import time
import random
from collections import Counter
import matplotlib.pyplot as plt
import seaborn as sns
from bs4 import BeautifulSoup
import os
import json
import argparse
import math

# Вывести уже обработанные данные (для отладки, не парсить так как долго)
OPTION_SKIP_PARSING = False

def get_vacancies(query, area, vacancies_limit=2000):
    """
    Собирает вакансии с HH.ru по заданному запросу.

    Args:
        query (str): Поисковый запрос (например, 'data scientist', 'machine learning').
        area (int): ID региона (например, 1 — Москва).
        vacancies_limit (int, optional):
            Ограничение по количеству вакансий. (value: 1 ~ 2000 [орграничение API HH])

    Returns:
        list: Список вакансий в формате JSON (каждая вакансия — словарь).
              Возвращает пустой список в случае ошибки или отсутствия вакансий.
    """
    #API: https://api.hh.ru/openapi/redoc#tag/Poisk-vakansij/operation/get-vacancies
    base_url = 'https://api.hh.ru/vacancies'
    params = {
        'text': query,
        'area': area,
        'per_page': 100,
        'page': 0,
        'search_fiels': "name"
    }

    # Ограничение кол-ва запросов
    pages_total = 0
    if vacancies_limit > 2000:
        print(
            'WARNING: Ограничение по количеству вакансий API hh.ru в 2000. '
            'Выбрано максимально допустимое значение')
        vacancies_limit = 2000
    elif vacancies_limit <= 0:
        raise Exception("CRITICAL_ERROR: vacancies_limit должно быть натуральным числом.")
    pages_total = math.ceil(vacancies_limit / params['per_page'])

    all_vacancies = []
    for page_current in range(pages_total):
        params['page'] = page_current
        try:
            data = fetch_data(base_url, params)
            items = data.get('items', [])
            if not items:
                break
            all_vacancies.extend(items)
            print(f"Обработана страница {page_current + 1} по запросу '{query}'")
            # задержка чтоб не быть забанеными сервером удаленным, не наглеем :)
            time.sleep(random.uniform(0.5, 1.0))

        except requests.exceptions.RequestException as e:
            print(f"Ошибка при запросе: {e}")
            continue

    return all_vacancies

def load_skills_whitelist(path="skills_whitelist.txt"):
    """
    Загружает белый список навыков из файла.

    Строки, начинающиеся с '#', считаются комментариями и игнорируются.
    Пустые строки также пропускаются.
    Все навыки приводятся к нижнему регистру.

    Args:
        path (str, optional): Путь к файлу со списком навыков. Defaults to "skills_whitelist.txt".

    Returns:
        set: Множество навыков (в нижнем регистре).
    """
    try:
        with open(path, encoding='utf-8') as f:
            lines = [
                line.strip().lower()
                for line in f
                if line.strip() and not line.startswith('#')
            ]
        return set(lines)

    except FileNotFoundError:
        return set([])

def extract_skills(text, skill_whitelist):
    """
    Извлекает навыки из текста (прим. описание вакансии).

    Производит поиск по переданному списку навыков (skill_whitelist),
    регистронезависимо. Поддерживает многословные навыки (например, 'computer vision'),
    сортировка которых происходит по длине, чтобы избежать частичного совпадения
    (например, 'vision' внутри 'computer vision').

    Args:
        text (str): Текст (прим. описание вакансии).
        skill_whitelist (set or list): Множество или список допустимых навыков.

    Returns:
        list: Список найденных навыков (в нижнем регистре).
    """
    text_lower = text.lower()
    found_skills = []

    for skill in sorted(skill_whitelist, key=len, reverse=True):
        if skill in text_lower:
            found_skills.append(skill)
            text_lower = text_lower.replace(skill, " ")
    return found_skills

def load_queries(path="queries.txt"):
    """
    Загружает список поисковых запросов (названий вакансий) из файла.

    Строки, начинающиеся с '#', считаются комментариями и игнорируются.
    Пустые строки также пропускаются.

    Args:
        path (str, optional): Путь к файлу со списком запросов. Defaults to "queries.txt".

    Returns:
        list: Список строк — запросов для поиска вакансий.
              Если файл не найден, возвращается стандартный набор запросов.
    """
    try:
        with open(path, encoding='utf-8') as f:
            lines = [
                line.strip()
                for line in f
                if line.strip() and not line.startswith('#')
            ]
        return [q for q in lines if q]
    except FileNotFoundError:
        return ["DataScience", "Machine Learning", "ML Engineer", "Data Scientist", "AI Specialist"]

def save_progress(data, file_path="progress.json"):
    """Сохраняет текущий прогресс в JSON-файл."""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_progress(path="progress.json"):
    """Загружает прогресс из JSON-файла, если существует."""
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def cli_parse():
    """
    Парсит аргументы командной строки.

    Returns:
        argparse.Namespace:
            area (int): Зона поиска (API HH)
            output (str): Целевой файл для записи конечного результата
            vacancies_limit (int):
                Ограничение кол-ва вакансий на каждый поисковой запрос
            skills_show_count (int):
                Ограничение кол-ва навыков для отображения в конечном
                результате (графике)
    """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description=(
            'Программа собирает вакансии с сайта https://hh.ru по ключевым '
            'запросам (например, "DataScience", "ML Engineer"), извлекает '
            'из них **навыки**, и строит столбчатую диаграмму самых '
            'популярных навыков'
            '\n\n'
            'конфигурационные файлы:\n'
            '  queries.txt — список ключевых запросов для поиска вакансий\n'
            '  skills_whitelist.txt — список навыков для анализа [только для --mode description]'
    ))

    parser.add_argument('-o', '--output',
        default='hh_skills_bar_chart.png',
        help='Файл для вывода результата (%(default)s)')

    parser.add_argument('-a', '--area',
        type=int,
        default=1,
        help=(
            'ID города/региона поиска вакансий. '
            'Найти можно тут -> https://api.hh.ru/areas (по умолчанию %(default)s)'
    ))

    parser.add_argument('--vacancies-limit',
        dest="vacancies_limit",
        type=int,
        default=2000,
        help='Ограничение на количество вакансий для обработки (%(default)s)')

    parser.add_argument('--skills-show-count', '--skills-count',
        type=int,
        default=50,
        help='Количество отображаемых навыков в графике (%(default)s)')

    parser.add_argument('-m', '--mode',
        default='key-skills',
        choices=['key-skills', 'description'],
        help=(
            'Режим key-skills просматривает соответствующее поле в запросе и '
            'строит график популярности навыков без зависимости от конфигурационного '
            'файла skills_whitelist.txt \n'
            'Режим description анализирует текст описания вакансий и требует skills_whitelist.txt\n'
            '(key-skills)'
    ))

    return parser.parse_args()

def fetch_data(url, params={}):
    """
    Args:
        url (str): Url запрос
        params (object_query_params, optional): Параметры запроса. Query params.

    Returns:
        object: Полезные данные в случае успеха
    """
    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    return data

def get_skills_from_description(data):
    """
    Извлекает данные из поля description (API HH)

    Returns:
        list (str): Список навыков
    """
    skill_whitelist = load_skills_whitelist()
    if not skill_whitelist:
        raise Exception('CRITICAL_ERROR: Нет данных в файле "skills_whitelist.txt"')

    desc_html = data.get('description', '')
    soup = BeautifulSoup(desc_html, 'html.parser')
    text = soup.get_text()
    skills = extract_skills(text, skill_whitelist)
    return skills

def get_skills_from_key_skills(data):
    """
    Извлекает данные из поля key_skills (API HH)

    Returns:
        list (str): Список навыков
    """
    key_skills = data.get('key_skills')
    skills = [item['name'] for item in key_skills];
    return skills

def main():
    # Настройка параметров (конфигурация)
    settings = cli_parse()
    queries = load_queries()

    #FIXME: Ошибка - при смене mode не изменяются результаты
    # Загружаем прогресс
    progress = load_progress()
    processed_ids = set(progress.get('processed_vacancy_ids', []))
    skill_counter = Counter(progress.get('current_skill_counts', {}))

    # Парсинг
    if not OPTION_SKIP_PARSING:
        total_to_process = 0
        query_vacancy_map = {}

        print("Начинаю сбор вакансий...")
        for q in queries:
            vacancies = get_vacancies(
                q,
                area=settings.area,
                vacancies_limit=settings.vacancies_limit
            )
            query_vacancy_map[q] = vacancies
            total_to_process += len(vacancies)
            print(f"Загружено вакансий по запросу '{q}': {len(vacancies)}")

        print(f"\nВсего вакансий для обработки: {total_to_process}\n")

        current_processed = 0
        for q, vacancies in query_vacancy_map.items():
            print(f"\nНачинаю обработку вакансий по запросу '{q}'...")
            for v in vacancies:
                current_processed += 1
                vid = v['id']
                if vid in processed_ids:
                    # Обновляем прогресс, если вакансия уже была
                    if current_processed % 50 == 0 or current_processed == total_to_process:
                        print(f"  Обработано {current_processed}/{total_to_process} вакансий...")
                    continue  # Пропускаем, если вакансия уже обработана

                url = f'https://api.hh.ru/vacancies/{vid}'
                try:
                    data = fetch_data(url)
                    skills = None
                    match settings.mode:
                        case "description":
                            skills = get_skills_from_description(data)
                        case "key-skills":
                            skills = get_skills_from_key_skills(data)
                        case _:
                            raise Exception(
                                "CRITICAL_ERROR: CLI --mode -> Отсутствует handler."
                            )

                    # Обновляем счётчики
                    for skill in skills:
                        skill_counter[skill] += 1

                    # Отмечаем вакансию как обработанную
                    processed_ids.add(vid)

                    # Сохраняем прогресс
                    save_progress({
                        'processed_vacancy_ids': list(processed_ids),
                        'current_skill_counts': dict(skill_counter)
                    })

                except Exception as e:
                    print(f"Ошибка при извлечении навыков для вакансии {v['id']}: {e}")
                    continue

                # Выводим прогресс каждые 50 вакансий или в конце
                if current_processed % 50 == 0 or current_processed == total_to_process:
                    print(f"  Обработано {current_processed}/{total_to_process} вакансий...")

    print("\nВсе вакансии обработаны. Строю результаты...")

    # Сортировка
    sorted_skills = dict(sorted(skill_counter.items(), key=lambda x: x[1], reverse=True))

    # Ограничим до топ-N для графика
    top_n = dict(list(sorted_skills.items())[:settings.skills_show_count])

    # Сохраним весь список в файл на диск
    top_all = dict(list(sorted_skills.items()))
    df_all = pd.DataFrame(list(top_all.items()), columns=['Skill', 'Count'])
    df_all = df_all[['Count', 'Skill']]  # Поменять местами
    df_all['Count'] = pd.to_numeric(df_all['Count'])
    df_all_filename = 'top_skills_all_data.csv'
    df_all.to_csv(df_all_filename, index=False)
    print(f"\nВесь отсортированный список сохранен в файл {df_all_filename}")

    print(f"\nТоп-{settings.skills_show_count} навыков:")
    for skill, count in top_n.items():
        print(f"{skill}: {count}")

    # Построение графика
    df = pd.DataFrame(list(top_n.items()), columns=['Skill', 'Count'])
    df = df[['Count', 'Skill']]  # Поменять местами
    df['Count'] = pd.to_numeric(df['Count'])  # Преобразовать в числа
    df = df.sort_values('Count', ascending=False)

    height_per_skill = 0.45
    fig_height = max(10, len(df) * height_per_skill)
    plt.figure(figsize=(12, fig_height))

    ax = sns.barplot(data=df, y='Skill', x='Count', hue='Skill', legend=False, palette="viridis")

    plt.subplots_adjust(left=0.3, right=0.95, top=0.95, bottom=0.05)
    ax.tick_params(axis='y', labelsize=11)
    ax.tick_params(axis='x', labelsize=10)

    # Добавляем значения на бары
    for i, (count, skill) in enumerate(zip(df['Count'], df['Skill'])):
        count_int = int(count)
        ax.text(count_int + 10, i, str(count_int), va='center', fontsize=9, color='gray')

    plt.title("Частота упоминаний навыков в вакансиях (HH.ru)", fontsize=16, pad=20)
    plt.xlabel("Количество упоминаний", fontsize=14)
    plt.ylabel("Навыки", fontsize=14)
    plt.savefig(settings.output, dpi=150, bbox_inches='tight')
    print(f"\nГрафик сохранён как '{settings.output}'")

if __name__ == "__main__":
    main()
