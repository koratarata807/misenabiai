# restaurant_ai_pro/meo/google_client.py
"""
Google API クライアントモジュール

- GooglePlacesClient
    - Places API を使った店舗詳細取得・順位推定
- GoogleBusinessClient
    - Business Profile API を使った口コミ・投稿などの操作

※ 実運用には以下の環境変数が必要：
    - GOOGLE_PLACES_API_KEY
    - GMB_ACCESS_TOKEN  （OAuth で取得したアクセストークン）
    - GMB_ACCOUNT_ID    （例: 'accounts/123456789012345678901'）
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests


# ========== 共通ユーティリティ ==========

class GoogleApiError(Exception):
    """Google API 呼び出しに失敗した場合の例外"""
    pass


def _raise_for_error(resp: requests.Response, context: str) -> None:
    """エラー時に詳細付きで例外を投げる"""
    if 200 <= resp.status_code < 300:
        return
    try:
        detail = resp.json()
    except Exception:
        detail = resp.text
    raise GoogleApiError(f"[{context}] status={resp.status_code}, detail={detail}")


# ========== Places API クライアント ==========

class GooglePlacesClient:
    """
    Google Places API 用クライアント

    主な用途：
    - place_id から店舗詳細を取得
    - キーワード検索から自店舗の順位を推定
    """

    BASE_URL = "https://maps.googleapis.com/maps/api/place"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("GOOGLE_PLACES_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_PLACES_API_KEY が設定されていません。")

    # 店舗詳細取得
    def get_place_details(self, place_id: str) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/details/json"
        params = {
            "place_id": place_id,
            "key": self.api_key,
            # 必要に応じて fields を絞る
            "fields": "name,formatted_address,geometry,opening_hours,types,photos,rating,user_ratings_total",
        }
        resp = requests.get(url, params=params, timeout=10)
        _raise_for_error(resp, "PlacesDetails")
        data = resp.json()
        if data.get("status") != "OK":
            raise GoogleApiError(f"[PlacesDetails] status={data.get('status')}, error={data}")
        return data.get("result", {})

    # キーワード検索 → 順位推定
    def get_ranking(
        self,
        target_place_id: str,
        keyword: str,
        location: Optional[str] = None,
        radius: int = 3000,
    ) -> Optional[int]:
        """
        keyword でテキスト検索を行い、結果リストの中で target_place_id が
        何番目に出てくるかを返す（1始まりの順位）。見つからなければ None。

        location: "43.0618,141.3545" 形式（札幌中心など）
        radius: 検索半径（メートル）
        """
        url = f"{self.BASE_URL}/textsearch/json"
        params = {
            "query": keyword,
            "key": self.api_key,
        }
        if location:
            params["location"] = location
            params["radius"] = radius

        resp = requests.get(url, params=params, timeout=10)
        _raise_for_error(resp, "PlacesTextSearch")
        data = resp.json()
        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            raise GoogleApiError(f"[PlacesTextSearch] status={data.get('status')}, error={data}")

        results: List[Dict[str, Any]] = data.get("results", [])
        for idx, item in enumerate(results, start=1):
            if item.get("place_id") == target_place_id:
                return idx

        # 検索結果に出てこない場合
        return None


# ========== Business Profile API クライアント ==========

class GoogleBusinessClient:
    """
    Google Business Profile API 用クライアント

    主な用途：
    - 口コミ一覧取得
    - 投稿一覧取得
    - 投稿作成
    - 口コミ返信
    - メディア（写真）一覧取得（簡易）
    """

    # v4 系の Business API（口コミ・投稿周り）
    BASE_URL_MYBUSINESS = "https://mybusiness.googleapis.com/v4"

    def __init__(
        self,
        access_token: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> None:
        self.access_token = access_token or os.getenv("GMB_ACCESS_TOKEN")
        self.account_id = account_id or os.getenv("GMB_ACCOUNT_ID")

        if not self.access_token:
            raise ValueError("GMB_ACCESS_TOKEN が設定されていません。")
        if not self.account_id:
            raise ValueError("GMB_ACCOUNT_ID が設定されていません。 (例: 'accounts/123456...')")

    # 共通ヘッダ
    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    # location_id は "accounts/.../locations/..." 形式を想定
    # shops.yaml 側では "locations/XXXXXXXX" を持たせて、
    # ここで account_id と結合する運用もアリ。

    def _location_name(self, location_id: str) -> str:
        """
        location_id が "locations/XXXX" の場合など、
        account_id と結合して "accounts/XXX/locations/XXX" に正規化する。
        """
        if location_id.startswith("accounts/"):
            return location_id
        # 想定: location_id = "locations/1234567890"
        return f"{self.account_id}/{location_id}"

    # ---- 口コミ一覧取得 ----
    def list_reviews(self, location_id: str) -> List[Dict[str, Any]]:
        name = self._location_name(location_id)
        url = f"{self.BASE_URL_MYBUSINESS}/{name}/reviews"
        resp = requests.get(url, headers=self.headers, timeout=10)
        _raise_for_error(resp, "ListReviews")
        data = resp.json()
        return data.get("reviews", [])

    # ---- 口コミ返信 ----
    def reply_review(self, location_id: str, review_id: str, reply_text: str) -> None:
        """
        レビューに返信する。
        review_id: list_reviews で取得した review['reviewId'] など
        """
        name = self._location_name(location_id)
        url = f"{self.BASE_URL_MYBUSINESS}/{name}/reviews/{review_id}/reply"
        payload = {
            "comment": reply_text,
        }
        resp = requests.put(url, headers=self.headers, json=payload, timeout=10)
        _raise_for_error(resp, "ReplyReview")

    # ---- 投稿一覧取得 ----
    def list_posts(self, location_id: str) -> List[Dict[str, Any]]:
        """
        ローカル投稿一覧を取得
        """
        name = self._location_name(location_id)
        url = f"{self.BASE_URL_MYBUSINESS}/{name}/localPosts"
        resp = requests.get(url, headers=self.headers, timeout=10)
        _raise_for_error(resp, "ListPosts")
        data = resp.json()
        return data.get("localPosts", [])

    # ---- 投稿作成 ----
    def create_post(
        self,
        location_id: str,
        text: str,
        media_urls: Optional[List[str]] = None,
        call_to_action_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        シンプルなテキスト＋写真1〜数枚の投稿を作成する。
        media_urls: S3 等にホストされている画像URLリスト
        """
        name = self._location_name(location_id)
        url = f"{self.BASE_URL_MYBUSINESS}/{name}/localPosts"

        media_list = []
        for m in media_urls or []:
            media_list.append({
                "mediaFormat": "PHOTO",
                "sourceUrl": m,
            })

        body: Dict[str, Any] = {
            "summary": text,
        }
        if media_list:
            body["media"] = media_list
        if call_to_action_url:
            body["callToAction"] = {
                "actionType": "LEARN_MORE",
                "url": call_to_action_url,
            }

        resp = requests.post(url, headers=self.headers, json=body, timeout=10)
        _raise_for_error(resp, "CreatePost")
        return resp.json()

    # ---- 写真一覧取得（簡易） ----
    def list_photos(self, location_id: str) -> List[Dict[str, Any]]:
        """
        Business Profile 上のメディア（写真）一覧を返す。
        実際には Business Information API / Media API を併用するケースもあるが、
        ここでは My Business API の media を簡易に利用。
        """
        name = self._location_name(location_id)
        # v4 の media エンドポイントは環境によって異なるため、
        # ここは状況に応じて修正する前提の簡易版。
        url = f"{self.BASE_URL_MYBUSINESS}/{name}/media"
        resp = requests.get(url, headers=self.headers, timeout=10)
        if resp.status_code == 404:
            # メディアAPIが無効なアカウントなどの場合は空リストで返す
            return []
        _raise_for_error(resp, "ListPhotos")
        data = resp.json()
        return data.get("mediaItems", [])
