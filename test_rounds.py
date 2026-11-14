import unittest
from eliminations import parse_eliminations
from round_browser import get_rounds_from_select_html
from index_stats import enrich, driver_averages
import pandas as pd
E = {'name':'Example Divisional','kind':'Divisional','division':7,'url':'https://www.nhra.com/results/2026/lucas-oil-drag-racing-series/d7/20261105'}
URL=E['url']+'/detailed-results/super-comp'
HEAD='Lane Driver Car No. Class Dial In RT 60 FT 330 FT 660 FT 660 MPH 1000 FT ET MPH Ov/Un MOV First'.split('|')
COLS=['Lane','Driver','Car No.','Class','Dial In','RT','60 FT','330 FT','660 FT','660 MPH','1000 FT','ET','MPH','Ov/Un','MOV','First']
def row(values):
    return '<tr>'+''.join('<td>'+str(x)+'</td>' for x in values)+'</tr>'
def fixture(n):
    return '<table>'+row(COLS)+row(['Left','Gabriel Torres WIN','6','SC','9.05','.012','1.670','4.456','6.268','139.41','7.763',n,'179.33','-.031','.012','--'])+row(['Right','Other Racer','12','SC','9.05','.040','1.5','4.2','6.1','133','7.7','9.030','178','-.020','--','--'])+'</table>'
class TestAllRounds(unittest.TestCase):
    def test_round_selector(self):
        h='<select aria-label="Round"><option>Final</option><option>Round 1</option><option>Round 2</option><option>Qualifying 1</option></select>'
        ix, rounds = get_rounds_from_select_html(h)
        self.assertEqual(ix,0)
        self.assertEqual(len(rounds),3)
    def test_distinct_rounds_and_stats(self):
        one=parse_eliminations(fixture('9.019'),URL,E,'Super Comp','Round 1')
        two=parse_eliminations(fixture('9.032'),URL,E,'Super Comp','Round 2')
        self.assertEqual(len(one),2)
        self.assertEqual(len(two),2)
        self.assertNotEqual(one[0]['record_id'],two[0]['record_id'])
        frame=enrich(pd.DataFrame(one+two),'Super Comp')
        gab=frame[frame.driver=='Gabriel Torres']
        self.assertEqual(len(gab),2)
        self.assertAlmostEqual(gab.et_over_under.mean(),-.0245)
        averages=driver_averages(frame)
        self.assertEqual(averages[averages.driver=='Gabriel Torres'].iloc[0].passes,2)
if __name__=='__main__':unittest.main()
