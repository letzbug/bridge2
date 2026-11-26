from app.loop_detection import HistoryItem, LoopDetector, normalize, similarity

A = "Memory might be reconstructed each time, and dreaming could be one way of rehearsing social situations."
B = "Memory might be reconstructed each time, and dreaming could be one way of rehearsing social situations!"
C = "Let us instead look at how the length of answers changes when the attribution label is removed entirely."


def test_normalize_and_similarity():
    assert normalize("Hello,   WORLD!") == "hello world"
    assert similarity(A, B) == 1.0
    assert similarity(A, C) < 0.1
    assert similarity("", A) == 0.0


def test_exact_duplicate_across_turns():
    d = LoopDetector()
    v = d.check("guest", B, [HistoryItem(2, "guest", A)])
    assert v.kind == "exact_duplicate" and v.matched_turn == 2


def test_near_duplicate():
    d = LoopDetector(near_threshold=0.6)
    slightly = A.replace("social situations", "social situations again today")
    v = d.check("guest", slightly, [HistoryItem(4, "guest", A), HistoryItem(5, "host", C)])
    assert v.kind == "near_duplicate" and v.matched_turn == 4 and v.similarity >= 0.6


def test_echo_of_received_message():
    d = LoopDetector()
    v = d.check("host", A, [], received_text="Message from Gem:\n\n" + A)
    assert v.kind == "echo"
    quoting = "You said that " + " ".join(A.split()[:6]) + " – I disagree, because " + C
    assert not d.check("host", quoting, [], received_text="Message from Gem:\n\n" + A).triggered


def test_distinct_messages_pass_and_short_messages_only_exact():
    d = LoopDetector()
    assert not d.check("host", C, [HistoryItem(1, "host", A)]).triggered
    assert not d.check("host", "Thanks!", [HistoryItem(1, "host", "Thank you!")]).triggered
    assert d.check("host", "Thanks!", [HistoryItem(1, "host", "thanks")]).kind == "exact_duplicate"
