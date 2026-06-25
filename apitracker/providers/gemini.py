"""Tracked Google Gemini client.

Supports both Gemini Python SDKs, because they expose the call differently:

* New ``google-genai``::

      from google import genai
      from apitracker import Tracker
      from apitracker.providers import TrackedGemini

      tracker = Tracker()
      gem = TrackedGemini(tracker, app="myapp", client=genai.Client())
      resp = gem.models.generate_content(
          model="gemini-2.5-flash", contents="Hi",
      )

* Old ``google-generativeai``::

      import google.generativeai as genai
      from apitracker.providers import TrackedGemini

      genai.configure(api_key="...")
      gem = TrackedGemini(tracker, app="myapp",
                          client=genai.GenerativeModel("gemini-1.5-pro"))
      resp = gem.generate_content("Hi")

In both cases usage is recorded after each ``generate_content`` call. The model
name comes from the ``model=`` argument (new SDK) or the wrapped model's
``model_name`` (old SDK). Streaming calls (``generate_content_stream`` /
``stream=True``) are passed through unrecorded -- record their final aggregated
response via ``tracker.record_gemini(...)``.
"""

from __future__ import annotations

from typing import Optional

from ..tracker import Tracker


def _clean_model(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return name.split("/", 1)[1] if name.startswith("models/") else name


class TrackedGemini:
    def __init__(
        self,
        tracker: Tracker,
        *,
        app: Optional[str] = None,
        api_key: Optional[str] = None,
        client=None,
    ):
        if client is None:
            raise ValueError(
                "Pass client=<genai.Client() (new SDK) or "
                "genai.GenerativeModel(...) (old SDK)>"
            )
        self._client = client
        self._tracker = tracker
        self._app = app
        self._api_key = api_key

    @property
    def models(self):
        """New ``google-genai`` path: ``client.models.generate_content(...)``."""
        return _GeminiModels(
            self._client.models, self._tracker, self._app, self._api_key
        )

    def generate_content(self, *args, **kwargs):
        """Old ``google-generativeai`` path: ``GenerativeModel.generate_content(...)``."""
        response = self._client.generate_content(*args, **kwargs)
        model = kwargs.get("model") or _clean_model(
            getattr(self._client, "model_name", None)
        )
        if not kwargs.get("stream"):
            self._tracker.record_gemini(
                response, app=self._app, api_key=self._api_key, model=model
            )
        return response

    def __getattr__(self, name):
        return getattr(self._client, name)


class _GeminiModels:
    def __init__(self, raw, tracker: Tracker, app, api_key):
        self._raw = raw
        self._tracker = tracker
        self._app = app
        self._api_key = api_key

    def generate_content(self, *args, **kwargs):
        response = self._raw.generate_content(*args, **kwargs)
        self._tracker.record_gemini(
            response, app=self._app, api_key=self._api_key, model=kwargs.get("model")
        )
        return response

    def __getattr__(self, name):
        return getattr(self._raw, name)
