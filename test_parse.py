"""Offline check of the HTML parsing step, using markup shaped like the live page."""
from scrape import parse_offers, validate

FIXTURE = """
<ul>
<li><span>1</span>
  <a href="https://www.gambling.com/go/uk/mr-vegas/offer/8458#ctalocation=_&source=oplist"><img alt="Mr Vegas Casino"></a>
  <a href="https://www.gambling.com/go/uk/mr-vegas/offer/8458#ct=oplistclk&ctalocation=bonus-offer&source=oplist"><em>100%</em> up to <em>£50</em> + <em>11</em> Free Spins</a>
  <a href="https://www.gambling.com/uk/online-casinos/reviews/mr-vegas">Review</a>
  <p>18+. New players. Min deposit £10. Wager 10x the deposit.</p></li>
<li><span>2</span>
  <a href="https://www.gambling.com/go/uk/casumo/offer/9694#ctalocation=_"><img alt="Casumo Casino"></a>
  <a href="https://www.gambling.com/go/uk/casumo/offer/9694#ctalocation=bonus-offer"><em>50%</em> Welcome Bonus up to <em>£100</em></a>
  <p>18+. Min deposit £20. 10x wagering on bonus amount.</p></li>
<li><span>3</span>
  <a href="https://www.gambling.com/go/uk/kwiff/offer/9085#ctalocation=bonus-offer"><img alt="Kwiff Casino"> Wager <em>£20,</em> Get <em>200</em> Free Spins</a>
  <p>18+. Wager £20 on slots. No wagering on winnings.</p></li>
</ul>
"""

def test_parse_three_offers():
    offers = parse_offers(FIXTURE)
    assert [o["casino"] for o in offers] == ["Mr Vegas Casino", "Casumo Casino", "Kwiff Casino"]
    assert "100% up to £50" in offers[0]["offer_text"]
    assert "Min deposit £10" in offers[0]["terms_text"]
    assert "Min deposit £20" in offers[1]["terms_text"]

def test_validate():
    ok = validate({"welcome_bonus": "100% up to £50", "wagering_multiplier": 10, "minimum_deposit": "£10"})
    assert ok["wagering_multiplier"] == 10
    for bad in ({"welcome_bonus": "x", "wagering_multiplier": "10x"}, {"wagering_multiplier": 1}):
        try:
            validate(bad)
        except ValueError:
            continue
        raise AssertionError("expected ValueError")

if __name__ == "__main__":
    test_parse_three_offers(); test_validate(); print("ok")
