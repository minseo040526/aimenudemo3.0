import streamlit as st
import pandas as pd
import random
from PIL import Image
import itertools

# --- 1. 설정 및 데이터 로드 ---

# 파일명 정의
BAKERY_MENU_PATH = "Bakery_menu.csv"
DRINK_MENU_PATH = "Drink_menu.csv"
MENU_BOARD_1_PATH = "menu_board_1.png"
MENU_BOARD_2_PATH = "menu_board_2.png"

# 데이터 로드 및 전처리 (캐싱)
@st.cache_data
def load_data(file_path):
    """CSV 파일을 로드하고 'tags' 컬럼을 리스트로 전처리합니다."""
    try:
        df = pd.read_csv(file_path)
        # 태그 전처리: 공백 제거, '#' 제거, 리스트로 분리
        df['tags'] = df['tags'].astype(str).str.replace(' ', '').str.split(',')
        df['tags'] = df['tags'].apply(lambda x: [tag.lstrip('#') for tag in x if tag])
        
        # 전체 태그 목록 추출
        all_tags = set()
        for tags_list in df['tags'].dropna():
            all_tags.update(tags_list)
        return df, sorted(list(all_tags))
    except FileNotFoundError:
        st.error(f"⚠️ 오류: 파일 '{file_path}'을 찾을 수 없습니다. 파일을 확인해주세요.")
        return pd.DataFrame(), []

# 데이터 로드
bakery_df, all_bakery_tags = load_data(BAKERY_MENU_PATH)
drink_df, all_drink_tags = load_data(DRINK_MENU_PATH)

# 전체 태그 목록 (중복 제거)
ALL_TAGS = sorted(list(set(all_bakery_tags + all_drink_tags)))


# --- 2. 점수 계산 로직 ---

def calculate_score(item_df, selected_tags, sweetness_range):
    """
    아이템의 추천 점수를 계산합니다.
    - 태그 일치 점수: 선택된 태그가 아이템에 포함될 때마다 10점씩 부여
    - 당도 선호도 점수: 아이템의 당도가 선택된 범위에 포함되면 5점 부여 (필터링이 되기 때문에 굳이 필요 없지만, 유연성 확보)
    """
    
    # 당도 필터링: 점수 계산 전에 당도 범위에 벗어나는 항목은 0점 처리
    min_sweetness, max_sweetness = sweetness_range
    item_df['sweetness_match'] = item_df.apply(
        lambda row: 5 if min_sweetness <= row['sweetness'] <= max_sweetness else 0, axis=1
    )

    # 태그 일치 점수
    def tag_score(tags_list, selected_tags):
        if not tags_list:
            return 0
        return sum(10 for tag in selected_tags if tag in tags_list)

    item_df['tag_score'] = item_df['tags'].apply(
        lambda x: tag_score(x, selected_tags)
    )
    
    # 최종 점수
    item_df['total_score'] = item_df['tag_score'] + item_df['sweetness_match']
    
    return item_df


# --- 3. 메뉴 추천 함수 ---

def get_best_items(df, selected_tags, sweetness_range, limit=None, people=1):
    """조건에 맞는 메뉴를 점수순으로 정렬하여 추천합니다."""
    if df.empty:
        return pd.DataFrame()

    scored_df = calculate_score(df.copy(), selected_tags, sweetness_range)
    
    # 1차 필터링: 당도 범위에 맞는 메뉴만 선택 (sweetness_match > 0)
    filtered_df = scored_df[scored_df['sweetness_match'] > 0].sort_values(
        by='total_score', ascending=False
    ).reset_index(drop=True)

    # 2차 필터링: 선택된 태그와 일치하는 메뉴가 있다면 그 메뉴들을 우선 선택
    tag_matched_df = filtered_df[filtered_df['tag_score'] > 0]
    
    if tag_matched_df.empty:
        # 태그 일치 메뉴가 없다면, 당도만 맞는 전체 메뉴에서 점수순으로 선택
        final_recommendations = filtered_df.head(limit * people if limit is not None else len(filtered_df))
    else:
        # 태그 일치 메뉴가 있다면, 그 중에서 점수순으로 선택
        final_recommendations = tag_matched_df.head(limit * people if limit is not None else len(tag_matched_df))

    # 그래도 부족하면 1차 필터링 된 전체 메뉴에서 보충
    if limit is not None and len(final_recommendations) < limit * people:
        needed = limit * people - len(final_recommendations)
        # 이미 추천된 항목 제외하고 추가
        additional_items = filtered_df[
            ~filtered_df.index.isin(final_recommendations.index)
        ].head(needed)
        final_recommendations = pd.concat([final_recommendations, additional_items]).drop_duplicates(subset=['name'])


    # 인원수에 맞게/제한 수량에 맞게 최종 조정
    final_recommendations = final_recommendations.head(limit * people if limit is not None else len(final_recommendations))
    
    return final_recommendations[['category', 'name', 'price', 'sweetness', 'tags', 'total_score']]

def recommend_combinations(budget, people, selected_tags, sweetness_range):
    """
    예산, 인원수, 선호도에 맞춰 음료와 베이커리 조합 3가지를 추천합니다.
    조합 점수 = (베이커리 점수 합 + 음료 점수 합)
    """
    if bakery_df.empty or drink_df.empty:
        return []

    # 1. 개별 메뉴 점수 계산 및 필터링
    scored_bakery = calculate_score(bakery_df.copy(), selected_tags, sweetness_range)
    scored_drink = calculate_score(drink_df.copy(), selected_tags, sweetness_range)

    # 당도 범위에 맞는 메뉴만 선택 (sweetness_match > 0)
    filtered_bakery = scored_bakery[scored_bakery['sweetness_match'] > 0].sort_values('total_score', ascending=False)
    filtered_drink = scored_drink[scored_drink['sweetness_match'] > 0].sort_values('total_score', ascending=False)
    
    if filtered_bakery.empty or filtered_drink.empty:
        return []

    # 2. 조합 생성 및 점수 계산
    combinations = []
    
    # 인원수만큼 음료를 고르고, 1~4개 베이커리를 고르는 모든 조합을 시도
    # (효율을 위해 상위 N개 메뉴만 사용)
    TOP_N = 20 # 상위 20개 메뉴만 고려
    top_bakery = filtered_bakery.head(TOP_N)
    top_drink = filtered_drink.head(TOP_N)

    # 인원수만큼 음료 조합 생성
    drink_combinations = list(itertools.combinations_with_replacement(top_drink.itertuples(index=False), people))

    for drink_combo_tuple in drink_combinations:
        drink_combo = list(drink_combo_tuple)
        
        # 음료 조합의 총 가격과 점수
        drink_price_sum = sum(d.price for d in drink_combo)
        drink_score_sum = sum(d.total_score for d in drink_combo)

        # 예산이 이미 초과되면 다음 조합으로
        if drink_price_sum >= budget:
            continue

        # 베이커리는 1개부터 4개까지 조합 시도
        for k in range(1, 5): 
            for bakery_combo_tuple in itertools.combinations(top_bakery.itertuples(index=False), k):
                bakery_combo = list(bakery_combo_tuple)
                
                # 베이커리 조합의 총 가격과 점수
                bakery_price_sum = sum(b.price for b in bakery_combo)
                bakery_score_sum = sum(b.total_score for b in bakery_combo)
                
                total_price = drink_price_sum + bakery_price_sum
                
                if total_price <= budget:
                    total_score = drink_score_sum + bakery_score_sum
                    
                    # 메뉴 이름 리스트
                    drink_names = [d.name for d in drink_combo]
                    bakery_names = [b.name for b in bakery_combo]
                    
                    combinations.append({
                        'score': total_score,
                        'price': total_price,
                        'drinks': drink_names,
                        'bakeries': bakery_names
                    })

    # 점수 순으로 상위 3개 조합 정렬 및 선택
    combinations.sort(key=lambda x: x['score'], reverse=True)
    
    return combinations[:3]


# --- 4. Streamlit UI 구성 ---

st.set_page_config(
    page_title="AI 메뉴 추천 ☕️🍰",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("카페 AI 메뉴 추천 시스템 🤖")

# 사이드바: 사용자 입력 설정
with st.sidebar:
    st.header("🛒 설정")
    
    # 1. 예산 설정
    st.subheader("1. 예산 설정 (₩)")
    budget = st.slider("최대 예산", min_value=5000, max_value=50000, value=20000, step=1000)
    
    # 2. 인원 설정
    st.subheader("2. 인원 설정 (명)")
    people = st.slider("인원수", min_value=1, max_value=10, value=2)

    # 3. 당도 설정
    st.subheader("3. 당도 설정 (0:無糖 ~ 4:高糖)")
    sweetness_range = st.slider(
        "선호 당도 범위",
        min_value=0, max_value=4, value=(1, 3)
    )

    # 4. 해시태그 선택 (최대 3개)
    st.subheader("4. 해시태그 선택 (최대 3개)")
    selected_tags = st.multiselect(
        "원하는 키워드를 선택하세요 (최대 3개)",
        options=ALL_TAGS,
        max_selections=3
    )

    st.markdown("---")
    st.info("⬆️ 설정을 변경하시면 실시간으로 메뉴가 추천됩니다.")

# --- 5. 메인 탭 구성 ---

tab1, tab2, tab3, tab4 = st.tabs(["💡 조합 추천", "🍞 베이커리 추천", "🥤 음료 추천", "🖼️ 메뉴판 보기"])

# 탭 1: 조합 추천 (가장 복잡한 로직)
with tab1:
    st.header("✨ 예산 맞춤 음료 + 베이커리 조합 추천 (Top 3)")
    st.markdown(f"**💰 예산:** **₩{budget:,}** | **👨‍👩‍👧‍👦 인원:** **{people}명** | **🍬 당도:** **{sweetness_range[0]} ~ {sweetness_range[1]}** | **🏷️ 태그:** {', '.join(selected_tags) if selected_tags else '선택 안함'}")
    st.markdown("---")

    if not bakery_df.empty and not drink_df.empty:
        with st.spinner('최적의 조합을 계산 중...'):
            recommendations = recommend_combinations(budget, people, selected_tags, sweetness_range)

        if recommendations:
            for i, combo in enumerate(recommendations):
                col1, col2 = st.columns([1, 4])
                
                with col1:
                    st.metric(label=f"🏆 **{i+1}위 조합**", value=f"총 점수: {combo['score']:.1f}점", delta=f"총 가격: ₩{combo['price']:,}")

                with col2:
                    st.subheader(f"✅ 추천 조합 #{i+1} (총 가격: ₩{combo['price']:,})")
                    st.caption(f"**점수:** {combo['score']:.1f}점")
                    
                    st.markdown("##### 🥤 음료 메뉴")
                    for name in combo['drinks']:
                        st.markdown(f"- **{name}**")

                    st.markdown("##### 🍰 베이커리 메뉴")
                    for name in combo['bakeries']:
                        st.markdown(f"- **{name}**")
                
                if i < len(recommendations) - 1:
                    st.markdown("---")
        else:
            st.warning("선택하신 조건(예산/인원/당도)에 맞는 음료+베이커리 조합을 찾을 수 없습니다. 조건을 완화해주세요.")
    else:
        st.error("메뉴 데이터 파일 로드에 문제가 있어 조합 추천을 할 수 없습니다.")


# 탭 2: 베이커리 추천
with tab2:
    st.header("🍞 취향 저격 베이커리 추천")
    st.caption(f"선택한 조건에 맞춰 **최대 4개**의 베이커리/디저트 메뉴를 추천합니다.")
    st.markdown("---")

    recommended_bakeries = get_best_items(bakery_df, selected_tags, sweetness_range, limit=4)

    if not recommended_bakeries.empty:
        for i, row in recommended_bakeries.iterrows():
            st.markdown(f"#### {i+1}. {row['name']} (₩{row['price']:,})")
            st.markdown(f"**카테고리**: {row['category']} | **당도**: {row['sweetness']} | **점수**: {row['total_score']:.1f}점")
            st.markdown(f"**태그**: {', '.join(['#' + tag for tag in row['tags']])}")
            st.markdown("---")
    else:
        st.warning("선택하신 당도나 태그 조건에 맞는 베이커리 메뉴가 없습니다. 조건을 다시 설정해주세요.")


# 탭 3: 음료 추천
with tab3:
    st.header("🥤 취향 저격 음료 추천")
    st.caption(f"선택한 조건에 맞춰 **인원수({people}명)**에 맞게 음료 메뉴를 추천합니다. (같은 메뉴가 추천될 수 있습니다.)")
    st.markdown("---")
    
    # 인원수(people)에 맞춰 추천 수량 설정
    recommended_drinks = get_best_items(drink_df, selected_tags, sweetness_range, limit=1, people=people)

    if not recommended_drinks.empty:
        # 추천 메뉴의 이름과 수량을 카운트
        drink_counts = recommended_drinks['name'].value_counts()
        
        st.subheader(f"👨‍👩‍👧‍👦 총 {people}잔 추천")
        
        # DataFrame 형태로 출력
        display_df = pd.DataFrame({
            '메뉴': drink_counts.index,
            '수량': drink_counts.values
        })

        st.dataframe(display_df, hide_index=True, use_container_width=True)
        
        st.markdown("---")

        st.subheader("세부 추천 목록 (점수 기준)")
        # 세부 정보와 점수 출력
        for i, row in recommended_drinks.iterrows():
            st.markdown(f"#### 추천 {i+1} : {row['name']} (₩{row['price']:,})")
            st.markdown(f"**카테고리**: {row['category']} | **당도**: {row['sweetness']} | **점수**: {row['total_score']:.1f}점")
            st.markdown(f"**태그**: {', '.join(['#' + tag for tag in row['tags']])}")
            st.markdown("---")
            
    else:
        st.warning("선택하신 당도나 태그 조건에 맞는 음료 메뉴가 없습니다. 조건을 다시 설정해주세요.")

# 탭 4: 메뉴판 보기
with tab4:
    st.header("🖼️ 메뉴판 사진")
    
    # 메뉴판 1
    try:
        image1 = Image.open(MENU_BOARD_1_PATH)
        st.image(image1, caption='메뉴판 1', use_column_width=True)
        st.markdown("---")
    except FileNotFoundError:
        st.warning(f"⚠️ 파일 '{MENU_BOARD_1_PATH}'을 찾을 수 없습니다.")

    # 메뉴판 2
    try:
        image2 = Image.open(MENU_BOARD_2_PATH)
        st.image(image2, caption='메뉴판 2', use_column_width=True)
    except FileNotFoundError:
        st.warning(f"⚠️ 파일 '{MENU_BOARD_2_PATH}'을 찾을 수 없습니다.")

# --- 코드 실행 방법 ---
# 1. 이 코드를 app.py로 저장합니다.
# 2. Bakery_menu.csv, Drink_menu.csv, menu_board_1.png, menu_board_2.png 파일을 같은 폴더에 둡니다.
# 3. 터미널에서 다음 명령어를 실행합니다:
#    streamlit run app.py