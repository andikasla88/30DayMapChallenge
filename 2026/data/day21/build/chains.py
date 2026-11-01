"""Day 21: the bubble tea chains we look for, and how each one should be tagged.

brand / name / qid, the chain's standard tags:
  nsi=True   the Name Suggestion Index entry (for Singapore, or worldwide if it has none for Singapore);
  otherwise  the chain's Wikidata item and its English label, or, with no Wikidata item (qid None:
             none found by fetch.py's search on 1 Nov 2026), the spelling OSM's own name and brand tags
             use most. process.py checks each of these and stops if one no longer holds.
  With qid None, "missing brand:wikidata" is not counted as a gap: there is nothing to link to yet.
match: a regex run, case-blind, over name, name:en, name:zh, brand and official_name.
not_: a regex that vetoes a match (another business with a similar name).
fill / ink: the chain's pastel colour and a darker shade of it for outlines and text.
"""

CHAINS = [
    dict(id='liho', label='LiHO', brand='LiHO', name='LiHO', qid=None, nsi=False,
         match=r'(?<![a-z])li-?ho(?![a-z])', fill='#F6B3B9', ink='#B4535E'),
    dict(id='koi', label='KOI Thé', brand='KOI Thé', name='KOI Thé', qid='Q56393853', nsi=False,
         match=r'(?<![a-z])koi(?![a-z])', not_=r'izakaya|pond|pong|fish|carp|farm|koil', fill='#F7D58B', ink='#A6741C'),
    dict(id='gongcha', label='Gong Cha', brand='Gong Cha', name='Gong Cha', qid='Q5581670', nsi=True,
         match=r'gong\s?cha|貢茶|贡茶', fill='#E9A7A0', ink='#A2483E'),
    dict(id='chicha', label='Chicha San Chen', brand='Chicha San Chen', name='Chicha San Chen', qid='Q133042869', nsi=True,
         match=r'chi\s?cha\s?san\s?chen|吃茶三千', fill='#F5C2A2', ink='#AE5F31'),
    dict(id='mixue', label='Mixue', brand='Mixue Ice Cream & Tea', name='Mixue', qid='Q107406476', nsi=True,
         match=r'mixue|蜜雪|(?<![a-z])mxbc(?![a-z])', fill='#F4A3BF', ink='#B03D67'),
    dict(id='chagee', label='Chagee', brand='Chagee', name='Chagee', qid='Q125052867', nsi=True,
         match=r'chagee|霸王茶姬|ba\s?wang\s?cha\s?ji', fill='#A9C7E8', ink='#3E6E9E'),
    dict(id='itea', label='iTea', brand='iTea', name='iTea', qid=None, nsi=False,
         match=r'^\s*i[\s.\-]?tea(?![a-z])|爱茶', fill='#B9DFA6', ink='#4F8A35'),
    dict(id='rnb', label='R&B Tea', brand='R&B Tea', name='R&B Tea', qid='Q124094218', nsi=False,
         match=r'r\s?&\s?b\s?(tea|巡茶)|巡茶', fill='#C9B3E6', ink='#6E4FA0'),
    dict(id='eachacup', label='Each A Cup', brand='Each A Cup', name='Each A Cup', qid=None, nsi=False,
         match=r'each[\s-]?a[\s-]?cup', fill='#A8DCD1', ink='#2F8475'),
    dict(id='playmade', label='Playmade', brand='Playmade', name='Playmade', qid=None, nsi=False,
         match=r'play\s?made', fill='#9FD3EA', ink='#2B7FA3'),
    dict(id='sharetea', label='Sharetea', brand='Sharetea', name='Sharetea', qid='Q64827032', nsi=True,
         match=r'share\s?tea|歇腳亭', fill='#D7C29B', ink='#86683A'),
    dict(id='yifang', label='Yi Fang', brand='Yi Fang Tea', name='Yi Fang Tea', qid='Q66196395', nsi=True,
         match=r'yi\s?fang\s?(taiwan\s?)?(fruit\s?)?tea|一芳水果茶', fill='#F2B98A', ink='#A65B22'),
    dict(id='heylongcha', label='Hey Long Cha', brand='Hey Long Cha', name='Hey Long Cha', qid=None, nsi=False,
         match=r'hey\s?long\s?cha|黑龍茶|黑龙茶', fill='#B7B3A6', ink='#5E5A4E'),
    dict(id='yanxitang', label='Yan Xi Tang', brand='Yan Xi Tang', name='Yan Xi Tang', qid=None, nsi=False,
         match=r'yan\s?xi\s?tang|延禧堂', fill='#E3B8D8', ink='#94487F'),
    dict(id='partea', label='Partea', brand='Partea', name='Partea', qid=None, nsi=False,
         match=r'(?<![a-z])par\s?tea(?![a-z])', fill='#C4DB8E', ink='#64802A'),
    dict(id='hollin', label='Hollin', brand='Hollin', name='Hollin', qid=None, nsi=False,
         match=r'(?<![a-z])hollin(?![a-z])', fill='#A3C9C0', ink='#3D7569'),
    dict(id='milksha', label='Milksha', brand='Milksha', name='Milksha', qid='Q67934215', nsi=False,
         match=r'milksha|迷客夏', fill='#E8CBA9', ink='#8C6236'),
    dict(id='heytea', label='Heytea', brand='Heytea', name='Heytea', qid='Q60875376', nsi=True,
         match=r'(?<![a-z])hey\s?tea|喜茶', fill='#BFC6D6', ink='#4F5B78'),
    dict(id='tigersugar', label='Tiger Sugar', brand='Tiger Sugar', name='Tiger Sugar', qid='Q76099070', nsi=True,
         match=r'tiger\s?sugar|老虎堂', fill='#D9B08C', ink='#7E5230'),
    dict(id='tealive', label='Tealive', brand='Tealive', name='Tealive', qid='Q95722097', nsi=True,
         match=r'tealive', fill='#B5D4A0', ink='#4D7A33'),
    dict(id='alley', label='The Alley', brand='The Alley', name='The Alley', qid='Q126456355', nsi=True,
         match=r'^the\s?alley$|鹿角巷', fill='#C9C0B0', ink='#6B5F4A'),
    dict(id='kungfu', label='Kung Fu Tea', brand='Kung Fu Tea', name='Kung Fu Tea', qid='Q66023886', nsi=True,
         match=r'kung\s?fu\s?tea', fill='#E7A9A9', ink='#9A4545'),
    dict(id='chatime', label='Chatime', brand='Chatime', name='Chatime', qid='Q16829306', nsi=True,
         match=r'chatime|日出茶太', fill='#D4B6E2', ink='#7B4B93'),
]
