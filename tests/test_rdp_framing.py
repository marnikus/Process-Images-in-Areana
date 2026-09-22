"""RDP wire codec: `<byte-length>:<json>`, and reply-vs-event by shape.

The two properties that make this protocol easy to get silently wrong:
the prefix counts **bytes** (not characters), and a reply is distinguished
from an unsolicited event by the **absence of `type`**, not by the sender.
"""

import json

import pytest

from app.browser.rdp.framing import (FramingError, decode_packets, encode_packet, is_event,
                                     is_reply_from)

pytestmark = pytest.mark.unit


def test_a_packet_is_framed_with_its_byte_length():
    raw = encode_packet({"to": "root", "type": "listTabs"})
    head, _, body = raw.partition(b":")
    assert int(head) == len(body)
    assert json.loads(body) == {"to": "root", "type": "listTabs"}


def test_outbound_frames_are_escaped_to_ascii_so_the_prefix_cannot_desync():
    """We emit \\uXXXX escapes, so the byte count and the character count agree."""
    raw = encode_packet({"to": "root", "text": "café ☕"})
    head, _, body = raw.partition(b":")
    assert int(head) == len(body) and body.isascii()
    assert decode_packets(raw)[0][0]["text"] == "café ☕"


def test_an_inbound_frame_of_raw_utf8_is_measured_in_bytes():
    """Firefox sends real UTF-8 (a page title), where bytes > characters."""
    body = '{"from":"root","title":"café ☕"}'.encode("utf-8")
    assert len(body) > len(body.decode("utf-8"))
    frame = str(len(body)).encode("ascii") + b":" + body
    packets, rest = decode_packets(frame)
    assert packets[0]["title"] == "café ☕" and rest == b""


def test_a_prefix_that_counted_characters_leaves_the_stream_desynced():
    """The failure this guards: a short count truncates and corrupts what follows."""
    body = '{"from":"root","title":"café ☕"}'.encode("utf-8")
    bad = str(len(body.decode("utf-8"))).encode("ascii") + b":" + body
    with pytest.raises(FramingError):
        decode_packets(bad + encode_packet({"from": "tab1"}))


def test_decode_returns_whole_packets_and_keeps_the_partial_tail():
    stream = encode_packet({"from": "root"}) + encode_packet({"from": "tab1"})
    packets, rest = decode_packets(stream[:-4])
    assert packets == [{"from": "root"}] and rest == stream[len(encode_packet({"from": "root"})):-4]
    packets2, rest2 = decode_packets(rest + stream[-4:])
    assert packets2 == [{"from": "tab1"}] and rest2 == b""


def test_an_empty_or_partial_buffer_is_empty_not_broken():
    """RULE 4: nothing to decode yet is a normal stream state, never an error."""
    assert decode_packets(b"") == ([], b"")
    assert decode_packets(b"25:{\"from\"") == ([], b"25:{\"from\"")


@pytest.mark.parametrize("bad", [b"nonsense-with-no-colon-at-all-here-and-more",
                                 b"abc:{}", b"999999999999:{}"])
def test_a_corrupt_stream_raises_rather_than_guessing(bad):
    with pytest.raises(FramingError):
        decode_packets(bad)


def test_undecodable_json_is_reported_not_swallowed():
    with pytest.raises(FramingError):
        decode_packets(b"5:{ bad")


def test_an_event_is_told_from_a_reply_by_shape_not_by_sender():
    """The same actor sends both; only the reply lacks `type` (the wrong-answer bug)."""
    reply = {"from": "console1", "resultID": "r1"}
    event = {"from": "console1", "type": "consoleAPICall"}
    assert is_reply_from(reply, "console1") and not is_event(reply)
    assert is_event(event) and not is_reply_from(event, "console1")


def test_a_reply_from_another_actor_is_not_ours():
    assert not is_reply_from({"from": "other"}, "console1")
    assert not is_reply_from({"from": "console1"}, "")
