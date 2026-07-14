# =========================
# TES WEBSOCKET RELAY /ws/ihsg
# =========================
# App ini MURNI relay stream ShadowStream (via Redis pub/sub) -> klien
# WebSocket -- tidak menghasilkan/mengarang data pasar. Relay pub/sub
# penuh diverifikasi live end-to-end (butuh Redis + subscriber async yang
# tidak ditiru _FakeRedis). Tes di sini menjaga bagian yang DETERMINISTIK:
# endpoint menerima koneksi & mengirim SNAPSHOT awal (dari key Redis) ke
# klien yang baru connect, verbatim.
import json


def test_ws_ihsg_sends_snapshot_on_connect(client):
    """Klien yang baru connect harus langsung menerima snapshot terakhir
    (kalau ShadowStream menyimpannya di key Redis) -- supaya tidak layar
    kosong sampai tick berikutnya. Verbatim: apa yang tersimpan = apa yang
    diterima klien."""
    import web.app as app_module
    from core.config import IHSG_SNAPSHOT_KEY

    payload = json.dumps({
        "type": "snapshot",
        "data": {"BBCA": {"ticker": "BBCA", "price": 9500,
                          "bid_5": [{"price": 9490, "volume": 1200, "freq": 8}],
                          "offer_5": [{"price": 9510, "volume": 1500, "freq": 10}]}},
    })
    # _FakeRedis (autouse fixture no_network) -- taruh snapshot langsung di store
    app_module._redis.store[IHSG_SNAPSHOT_KEY] = payload

    with client.websocket_connect("/ws/ihsg") as ws:
        received = json.loads(ws.receive_text())

    assert received["type"] == "snapshot"
    assert "BBCA" in received["data"]
    assert received["data"]["BBCA"]["offer_5"][0]["price"] == 9510


def test_ws_ihsg_connects_without_snapshot(client):
    """Tanpa snapshot tersimpan, koneksi TETAP diterima (tidak crash) --
    klien cuma menunggu tick berikutnya. Regresi: snapshot opsional, bukan
    syarat koneksi."""
    import web.app as app_module
    from core.config import IHSG_SNAPSHOT_KEY

    app_module._redis.store.pop(IHSG_SNAPSHOT_KEY, None)
    # Tidak boot lifespan/pump -- cukup pastikan handshake WS sukses.
    with client.websocket_connect("/ws/ihsg") as ws:
        assert ws is not None  # handshake berhasil = tidak ada exception
