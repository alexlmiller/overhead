"""Provider separation, flight matching, and durable spending guards."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('routes_model', Path(__file__).resolve().parents[1]/'custom_components/office_aircraft_routes/model.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
NOW = m.timestamp('2026-09-24T20:00:00Z')
PRIVATE = {'hex':'aabbcc','callsign':'N207BC','registration':'N207BC','observed':m.timestamp('2026-09-24T19:03:00Z'),'live':False,'inside':True}
FLIGHT = {'registration':'N207BC','type':'General_Aviation','actual_off':'2026-09-24T16:40:56Z','actual_on':'2026-09-24T19:10:22Z',
          'origin':{'code':'KDTO','code_iata':None},'destination':{'code':'KBZN','code_iata':'BZN'}}
AIRLINE = {'hex':'112233','callsign':'UAL2202','registration':'N123UA','latitude':45.78,'longitude':-111.15,'observed':NOW,'inside':True,'live':True}
CHAIN = {'callsign':'UAL2202','plausible':True,'_airports':[
    {'iata':'BZN','lat':45.7775,'lon':-111.153},{'iata':'ORD','lat':41.9786,'lon':-87.9048},{'iata':'IAD','lat':38.9445,'lon':-77.455803}]}

# Public AA2939 standing-data chain, inspected 2026-09-24. Positions below use
# the public Bozeman city center, not the household's coordinates.
AA2939 = {'callsign':'AAL2939','_airports':[
    {'iata':'DFW','lat':32.896801,'lon':-97.038002},
    {'iata':'FCA','lat':48.310501,'lon':-114.255997},
    {'iata':'DFW','lat':32.896801,'lon':-97.038002}]}
PASSING = {**AIRLINE,'callsign':'AAL2939','latitude':45.68,'longitude':-111.04,'speed_kt':450}
# Chains inspected 2026-09-24. ASA420 passed Bozeman 70 mi from its great circle;
# FDX90's live position (south of Helena) was 492 mi from PVG-MEM; DAL1205 is stale.
ASA420 = {'callsign':'ASA420','_airports':[
    {'iata':'SEA','lat':47.449001,'lon':-122.308998},{'iata':'MCO','lat':28.429399,'lon':-81.308998}]}
FDX90 = {'callsign':'FDX90','_airports':[
    {'iata':'PVG','lat':31.1434,'lon':121.805},{'iata':'MEM','lat':35.0424,'lon':-89.9767}]}
DAL1205 = {'callsign':'DAL1205','_airports':[
    {'iata':'PBI','lat':26.6832,'lon':-80.0956},{'iata':'BOS','lat':42.3643,'lon':-71.0052}]}
SLC, BZN = {'iata':'SLC','lat':40.788399,'lon':-111.977997}, {'iata':'BZN','lat':45.7775,'lon':-111.153}
SKW3676 = {'callsign':'SKW3676','_airports':[SLC,BZN,SLC]}
NEAR_BZN = {**AIRLINE,'callsign':'SKW3676','registration':'N288SY','latitude':45.60,'longitude':-111.10,
            'heading':340,'speed_kt':200,'altitude_ft':9000}
BOARD = '''<div class="current-date">September 24, 2026</div><span class="current-time">2:00PM</span>
<div id="arrivals-data"><div class="group flight-row" title="United - 741 - Denver - 1:33PM - Arrived"></div>
<div class="group flight-row" title="Southwest - 1255 - Denver - 2:03PM - Now 2:03 P"></div>
<div class="day-divider"></div><div class="group flight-row" title="Delta - 999 - Atlanta - 2:00PM - On Time"></div></div>
<div id="departures-data"><div class="group flight-row" title="Southwest - 1509 - Denver - 1:35PM - Departed"></div>
<div class="group flight-row" title="Delta - 111 - Atlanta - 2:00PM - Cancelled"></div></div>'''


class ModelTests(unittest.TestCase):
    def test_airport_board_is_dated_and_excludes_future_day_and_cancelled_rows(self):
        rows=m.airport_board(BOARD,NOW)
        self.assertEqual({r['flight'] for r in rows},{'UAL741','SWA1255','SWA1509'})
        self.assertEqual(m.airport_board(BOARD,NOW+901),[])
        self.assertEqual(m.airport_board(BOARD.replace('September 24','September 23'),NOW),[])
        self.assertEqual(m.airport_board('<html>unavailable</html>',NOW),[])

    def test_airport_board_matches_arrival_departure_and_prior_sighting(self):
        rows=m.airport_board(BOARD,NOW)
        departure={**AIRLINE,'callsign':'SWA1509','altitude_ft':8500}
        r=m.airport_route(rows,departure)
        self.assertEqual((r['origin'],r['destination']),('BZN','DEN'))
        arrival={**PRIVATE,'callsign':'UAL741','observed':NOW-39*60}
        r=m.airport_route(rows,arrival)
        self.assertEqual((r['origin'],r['destination']),('DEN','BZN'))
        self.assertIsNone(m.airport_route(rows,{**departure,'observed':NOW+2*m.DAY}))
        self.assertIsNone(m.airport_route(rows,{**departure,'altitude_ft':35000}))
        self.assertIsNone(m.airport_route(rows,{**departure,'latitude':40}))
        self.assertIsNone(m.airport_route(rows+[{**r,'flight':'SWA1509','valid_from':NOW-10000,'valid_until':NOW+10000}],departure))

    def test_classifier_never_paid_fallback_for_airline_or_unknown(self):
        self.assertEqual(m.provider(AIRLINE),'adsblol')
        self.assertEqual(m.provider(PRIVATE),'flightaware')
        self.assertEqual(m.provider({'callsign':'CFABC','registration':'C-FABC'}),'flightaware')
        self.assertIsNone(m.provider({'callsign':'AMBIGUOUS'}))
        self.assertIsNone(m.provider({'callsign':'../../bad','registration':'N207BC'}))

    def test_private_actual_time_match_and_sanitization(self):
        rows=m.private_routes({'flights':[FLIGHT]},'N207BC',NOW)
        route=m.match_private(rows,PRIVATE['observed'])
        self.assertEqual((route['origin'],route['destination']),('KDTO','BZN'))
        self.assertIsNone(m.match_private(rows,NOW))
        for patch in ({'type':'Airline'},{'registration':'N11111'},{'actual_off':None},{'cancelled':True},{'diverted':True}):
            self.assertEqual(m.private_routes({'flights':[{**FLIGHT,**patch}]},'N207BC',NOW),[])
        self.assertIsNone(m.match_private(rows+rows,PRIVATE['observed']))
        self.assertNotIn('registration',route)

    def test_airline_adjacent_leg_and_local_plausibility(self):
        r=m.commercial_route(CHAIN,AIRLINE)
        self.assertEqual((r['origin'],r['destination']),('BZN','ORD'))
        self.assertIsNone(m.commercial_route(CHAIN,{**AIRLINE,'latitude':10,'longitude':10}))
        self.assertIsNone(m.commercial_route(CHAIN,{**AIRLINE,'latitude':41.9786,'longitude':-87.9048}))
        self.assertIsNone(m.commercial_route(CHAIN,{**AIRLINE,'callsign':'UAL9999'}))
        self.assertIsNone(m.commercial_route({'callsign':'UAL2202','_airports':[{}]},AIRLINE))

    def test_aa2939_impossible_florida_route_is_rejected_even_if_provider_says_plausible(self):
        wrong={'callsign':'AAL2939','plausible':True,'_airports':[
            {'iata':'FLL','lat':26.072599,'lon':-80.152702},
            {'iata':'DCA','lat':38.8521,'lon':-77.037697}]}
        self.assertIsNone(m.commercial_route(wrong,{**PASSING,'heading':130}))

    def test_same_callsign_roundtrip_uses_ground_track_to_choose_direction(self):
        for heading,expected in [(130,('FCA','DFW')),(310,('DFW','FCA'))]:
            r=m.commercial_route(AA2939,{**PASSING,'heading':heading})
            self.assertEqual((r['origin'],r['destination']),expected)
        for heading in (None,-1,361,float('nan'),True):
            self.assertIsNone(m.commercial_route(AA2939,{**PASSING,'heading':heading}))
        self.assertIsNone(m.commercial_route(AA2939,{**PASSING,'heading':130,'speed_kt':80}))
        self.assertIsNone(m.commercial_route(AA2939,{**PASSING,'heading':130,'latitude':48.31,'longitude':-114.256}))

    def test_single_leg_in_the_wrong_direction_and_repeated_roundtrip_legs(self):
        outbound={**AA2939,'_airports':AA2939['_airports'][:2]}
        self.assertIsNone(m.commercial_route(outbound,{**PASSING,'heading':130}))
        repeated={**AA2939,'_airports':AA2939['_airports']+AA2939['_airports'][1:]}
        r=m.commercial_route(repeated,{**PASSING,'heading':130})
        self.assertEqual((r['origin'],r['destination']),('FCA','DFW'))

    def test_long_legs_allow_airway_and_weather_detours_but_not_stale_routes(self):
        cruise={**AIRLINE,'speed_kt':450,'altitude_ft':36000}
        r=m.commercial_route(ASA420,{**cruise,'callsign':'ASA420','latitude':45.68,'longitude':-111.04,'heading':115})
        self.assertEqual((r['origin'],r['destination']),('SEA','MCO'))
        r=m.commercial_route(FDX90,{**cruise,'callsign':'FDX90','latitude':46.65,'longitude':-112.67,'heading':108})
        self.assertEqual((r['origin'],r['destination']),('PVG','MEM'))
        self.assertIsNone(m.commercial_route(DAL1205,{**cruise,'callsign':'DAL1205','latitude':45.68,'longitude':-111.04,'heading':80}))

    def test_round_trip_near_the_shared_airport_uses_climb_or_descent(self):
        for rate,expected in [(-900,('SLC','BZN')),(700,('BZN','SLC')),(2500,('BZN','SLC'))]:
            r=m.commercial_route(SKW3676,{**NEAR_BZN,'vertical_rate':rate})
            self.assertEqual((r['origin'],r['destination']),expected)
        level={**NEAR_BZN,'vertical_rate':0}
        self.assertIsNone(m.commercial_route(SKW3676,level))
        self.assertIsNone(m.commercial_route(SKW3676,{**NEAR_BZN,'vertical_rate':None}))
        r=m.commercial_route(SKW3676,level,('SLC','BZN'))
        self.assertEqual((r['origin'],r['destination']),('SLC','BZN'))
        self.assertIsNone(m.commercial_route(SKW3676,level,('BZN','DEN')))

    def test_single_leg_is_not_shown_for_the_opposite_direction_near_an_airport(self):
        inbound={'callsign':'SKW3676','_airports':[SLC,BZN]}
        self.assertIsNone(m.commercial_route(inbound,{**NEAR_BZN,'vertical_rate':2500}))
        self.assertEqual(m.commercial_route(inbound,{**NEAR_BZN,'vertical_rate':-800})['origin'],'SLC')
        self.assertEqual(m.commercial_route(inbound,NEAR_BZN)['origin'],'SLC')

    def test_cruising_overflight_is_not_arriving_at_the_airport_below(self):
        inbound={'callsign':'SKW3676','_airports':[SLC,BZN]}
        self.assertIsNone(m.commercial_route(inbound,{**NEAR_BZN,'altitude_ft':37000,'vertical_rate':0}))
        self.assertEqual(m.commercial_route(inbound,{**NEAR_BZN,'altitude_ft':12000})['destination'],'BZN')

    def test_observations_carry_a_finite_vertical_rate(self):
        base={'hex':'112233','flight':'UAL2202','lat':45.78,'lon':-111.15,'seen_pos':1,'alt_baro':10000}
        for extra,expected in [({'baro_rate':-640},-640),({'geom_rate':320},320),
                               ({'baro_rate':None,'geom_rate':-64},-64),({},None),({'baro_rate':'fast'},None)]:
            row=m.observations([{**base,**extra}],NOW,(45.78,-111.15),5,[],NOW)[0]
            self.assertEqual(row['vertical_rate'],expected)

    def test_regional_operator_matches_its_partner_marketed_board_row(self):
        rows=m.airport_board(BOARD.replace('United - 741 - Denver','Delta - 3676 - Salt Lake City'),NOW)
        arrival={**AIRLINE,'callsign':'SKW3676','altitude_ft':9000,'observed':NOW-39*60}
        r=m.airport_route(rows,arrival)
        self.assertEqual((r['origin'],r['destination'],r['flight']),('SLC','BZN','SKW3676'))
        self.assertEqual(m.airport_route(rows,{**arrival,'callsign':'DAL3676'})['origin'],'SLC')
        self.assertIsNone(m.airport_route(rows,{**arrival,'callsign':'SWA3676'}))
        conflict=rows+[{**rows[0],'flight':'UAL3676','origin':'DEN'}]
        self.assertIsNone(m.airport_route(conflict,arrival))

    def test_board_resolves_published_destination_labels_and_reports_unknown_ones(self):
        for label,code in {'Austin':'AUS','Charlotte':'CLT','Boise':'BOI','New York-LGA':'LGA',
                           'Washington D.C. - IAD':'IAD','Seattle/Tacoma':'SEA','Portland, OR':'PDX',
                           "Chicago-O'Hare":'ORD','Dallas Ft. Worth':'DFW','Phoenix-Mesa':'AZA'}.items():
            self.assertEqual(m.board_city(label),code)
        self.assertIsNone(m.board_city('Portland, ME'))
        unmapped=set()
        board=BOARD.replace('United - 741 - Denver','United - 741 - Timbuktu').replace('Southwest - 1509','Acme Air - 1509')
        self.assertEqual({r['flight'] for r in m.airport_board(board,NOW,unmapped)},{'SWA1255'})
        self.assertEqual(unmapped,{'Timbuktu','Acme Air'})

    def test_board_rows_outlive_the_rolling_page_until_their_window_ends(self):
        first=m.airport_board(BOARD,NOW)
        self.assertEqual(m.merge_board(first,[],NOW+600),first)
        moved={**first[0],'valid_from':first[0]['valid_from']+900,'valid_until':first[0]['valid_until']+900}
        merged=m.merge_board(first,[moved],NOW)
        self.assertEqual(len(merged),len(first));self.assertIn(moved,merged)
        self.assertEqual(m.merge_board(first,[],NOW+7*3600),[])

    def test_observation_freshness_boundary_and_recent_history(self):
        raw=[{'hex':'112233','flight':'UAL2202 ','r':'N123UA','lat':45.78,'lon':-111.15,'seen_pos':1,'alt_baro':10000,'track':130,'gs':450}]
        history=[{**PRIVATE,'last_seen':PRIVATE['observed']}]
        rows=m.observations(raw,NOW,(45.78,-111.15),5,history,NOW)
        self.assertEqual(len(rows),2)
        self.assertTrue(rows[0]['inside'])
        self.assertEqual((rows[0]['heading'],rows[0]['speed_kt']),(130,450))
        self.assertEqual(m.observations(raw,NOW-30,(45.78,-111.15),5,history,NOW),[])
        self.assertEqual(len(m.observations([{**raw[0],'alt_baro':'ground'}],NOW,(45.78,-111.15),5,[],NOW)),0)

    def test_budget_persists_and_concurrent_reservations_cannot_overrun(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'ledger';ledger=m.Ledger(path)
            with ThreadPoolExecutor(max_workers=8) as pool:
                self.assertEqual(sum(pool.map(ledger.reserve,[NOW]*40)),25)
            self.assertEqual(m.Ledger(path).counts(NOW),(25,25))
            self.assertFalse(m.Ledger(path).reserve(NOW-100))
            self.assertTrue(m.Ledger(path).reserve(NOW+m.DAY+1))
            self.assertEqual(path.stat().st_mode&0o777,0o600)

    def test_rolling_period_limit_and_corrupt_db_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'ledger';ledger=m.Ledger(path)
            with ledger.connect() as db:
                db.executemany('INSERT INTO requests VALUES (?)',[(NOW-2*m.DAY,)]*800)
            self.assertFalse(ledger.reserve(NOW))
            self.assertTrue(ledger.reserve(NOW+31*m.DAY))
            path.write_bytes(b'corrupt budget')
            with self.assertRaises(Exception):m.Ledger(path)


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.ledger=m.Ledger(Path(self.tmp.name)/'ledger')
        self.calls=[]
        self.responses={'adsblol':(200,CHAIN),'flightaware':(200,{'flights':[FLIGHT]})}
        async def run(fn,*args):return fn(*args)
        async def request(provider,data):
            self.calls.append((provider,data));return self.responses[provider]
        self.engine=m.Enricher(self.ledger,run,request)

    async def asyncTearDown(self):self.tmp.cleanup()

    async def test_free_only_mode_never_requests_or_reserves_paid_lookups(self):
        self.engine=m.Enricher(self.ledger,self.engine.run,self.engine.request,use_flightaware=False)
        routes=await self.engine.tick([PRIVATE,AIRLINE],NOW)
        await self.engine.tick([PRIVATE,AIRLINE],NOW+30)
        self.assertEqual([p for p,_ in self.calls],['adsblol'])
        self.assertEqual(self.ledger.counts(NOW),(0,0))
        self.assertEqual({r['source'] for r in routes},{'ADSB.lol'})

    async def test_split_providers_cache_across_restart(self):
        routes=await self.engine.tick([PRIVATE,AIRLINE],NOW)
        self.assertEqual({r['source'] for r in routes},{'ADSB.lol','FlightAware'})
        self.assertEqual([p for p,_ in self.calls],['adsblol','flightaware'])
        self.assertEqual(self.ledger.counts(NOW),(1,1))
        self.engine=m.Enricher(m.Ledger(self.ledger.path),self.engine.run,self.engine.request)
        await self.engine.tick([PRIVATE,AIRLINE],NOW+30)
        self.assertEqual(len(self.calls),2)
        self.assertNotIn('latitude',routes[0])

    async def test_airline_miss_never_uses_flightaware(self):
        self.responses['adsblol']=(200,{})
        await self.engine.tick([AIRLINE],NOW)
        await self.engine.tick([AIRLINE],NOW+30)
        self.assertEqual([p for p,_ in self.calls],['adsblol'])
        self.assertEqual(self.ledger.counts(NOW),(0,0))

    async def test_static_route_request_contains_no_aircraft_or_home_position(self):
        await self.engine.tick([AIRLINE],NOW)
        self.assertEqual(self.calls,[('adsblol',{'callsign':'UAL2202'})])

    async def test_static_404_is_cached_without_paid_fallback(self):
        self.responses['adsblol']=(404,None)
        await self.engine.tick([AIRLINE],NOW)
        await self.engine.tick([AIRLINE],NOW+60)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.ledger.counts(NOW),(0,0))

    async def test_invalidated_route_is_removed_immediately(self):
        rows=await self.engine.tick([AIRLINE],NOW)
        self.assertEqual(len([r for r in rows if not r.get('historical')]),1)
        rows=await self.engine.tick([{**AIRLINE,'latitude':10,'longitude':10}],NOW+5)
        self.assertEqual([r for r in rows if not r.get('historical')],[])
        self.assertEqual(len(rows),1)  # The earlier sighting retains its route.
        self.assertEqual(len(self.calls),1)  # Cached data is revalidated locally.

    async def test_recent_route_survives_later_live_positions_and_restart(self):
        await self.engine.tick([AIRLINE],NOW)
        later={**AIRLINE,'inside':False,'observed':NOW+300}
        rows=await self.engine.tick([later],NOW+300)
        current=next(r for r in rows if not r.get('historical'))
        past=next(r for r in rows if r.get('historical'))
        self.assertGreater(current['valid_from'],NOW)
        self.assertLessEqual(past['valid_from'],NOW)
        self.assertGreaterEqual(past['valid_until'],NOW)
        restarted=m.Ledger(self.ledger.path).routes(NOW+360)
        self.assertIn(past,restarted)

    async def test_airport_supplement_backfills_history_without_paid_calls(self):
        self.engine.use_airport_board=True
        self.responses['bzn']=(200,{'routes':m.airport_board(BOARD,NOW)})
        history={**PRIVATE,'callsign':'UAL741','registration':'N39463','observed':NOW-39*60}
        rows=await self.engine.tick([history],NOW)
        self.assertEqual([(r['origin'],r['destination'],r['source']) for r in rows],[('DEN','BZN','BZN Airport')])
        self.assertEqual(self.calls,[('bzn',{})])
        await self.engine.tick([history],NOW+60)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.ledger.counts(NOW),(0,0))

    async def test_airport_live_route_overrides_static_route_and_reuses_cached_board(self):
        self.engine.use_airport_board=True
        self.responses['bzn']=(200,{'routes':m.airport_board(BOARD,NOW)})
        self.responses['adsblol']=(404,None)
        plane={**AIRLINE,'callsign':'SWA1509','altitude_ft':8500}
        rows=await self.engine.tick([plane],NOW)
        self.assertEqual({(r['origin'],r['destination']) for r in rows},{('BZN','DEN')})
        self.assertEqual([p for p,_ in self.calls],['adsblol','bzn'])
        await self.engine.tick([plane],NOW+30)
        self.assertEqual(len(self.calls),2)

    async def test_airport_denial_backs_off_without_paid_fallback(self):
        self.engine.use_airport_board=True
        self.responses['bzn']=(403,None)
        history={**PRIVATE,'callsign':'UAL741','registration':'N39463'}
        await self.engine.tick([history],NOW)
        await self.engine.tick([history],NOW+3600)
        self.assertEqual(self.calls,[('bzn',{})])

    async def test_departed_flight_keeps_its_board_route_after_leaving_the_page(self):
        self.engine.use_airport_board=True
        self.responses['adsblol']=(404,None)
        self.responses['bzn']=(200,{'routes':m.airport_board(BOARD,NOW),'unmapped':[]})
        plane={**AIRLINE,'callsign':'SWA1509','altitude_ft':8500}
        await self.engine.tick([plane],NOW)
        self.assertEqual(self.engine.status['bzn_unmapped'],'none')
        self.responses['bzn']=(200,{'routes':[],'unmapped':['Timbuktu']})
        rows=await self.engine.tick([{**plane,'observed':NOW+600}],NOW+600)
        self.assertEqual({(r['origin'],r['destination']) for r in rows},{('BZN','DEN')})
        self.assertEqual([p for p,_ in self.calls],['adsblol','bzn','bzn'])
        self.assertEqual(self.engine.status['bzn_unmapped'],'Timbuktu')

    async def test_route_chosen_en_route_survives_level_flight_near_the_airport(self):
        self.responses['adsblol']=(200,SKW3676)
        inbound={**NEAR_BZN,'latitude':45.1,'longitude':-111.3,'heading':10,'speed_kt':300,'vertical_rate':0}
        rows=await self.engine.tick([inbound],NOW)
        self.assertEqual({(r['origin'],r['destination']) for r in rows},{('SLC','BZN')})
        rows=await self.engine.tick([{**NEAR_BZN,'vertical_rate':0,'observed':NOW+300}],NOW+300)
        self.assertEqual([(r['origin'],r['destination']) for r in rows if not r.get('historical')],[('SLC','BZN')])

    async def test_failed_live_lookup_is_retried_for_the_recent_sighting(self):
        self.responses['adsblol']=(503,None)
        await self.engine.tick([AIRLINE],NOW)
        self.responses['adsblol']=(200,CHAIN)
        departed={'hex':'112233','callsign':'UAL2202','registration':'N123UA','observed':NOW,'live':False,'inside':True}
        rows=await self.engine.tick([departed],NOW+90)
        self.assertIn(('BZN','ORD'),{(r['origin'],r['destination']) for r in rows if r.get('historical')})
        self.assertEqual(len(self.calls),2)
        await self.engine.tick([departed],NOW+120)
        self.assertEqual(len(self.calls),2)  # Recovered once; cached data needs no new request.

    async def test_non_finite_feed_values_do_not_break_the_sighting_store(self):
        rows=await self.engine.tick([{**AIRLINE,'heading':float('nan'),'speed_kt':float('inf')}],NOW)
        self.assertEqual({(r['origin'],r['destination']) for r in rows},{('BZN','ORD')})
        self.assertIsNone(self.ledger.get('sighting:112233:UAL2202',NOW)['heading'])

    async def test_old_or_unseen_sightings_are_not_retried(self):
        self.responses['adsblol']=(503,None)
        await self.engine.tick([AIRLINE],NOW)
        departed={'hex':'112233','callsign':'UAL2202','registration':'N123UA','observed':NOW,'live':False,'inside':True}
        await self.engine.tick([departed],NOW+1801)
        await self.engine.tick([{**departed,'hex':'445566'}],NOW+90)
        self.assertEqual(len(self.calls),1)

    async def test_private_outside_boundary_does_not_cost(self):
        await self.engine.tick([{**PRIVATE,'inside':False,'live':True}],NOW)
        self.assertEqual(self.calls,[])

    async def test_failed_requests_are_counted_and_backoff_survives_restart(self):
        self.responses['flightaware']=(401,None)
        await self.engine.tick([PRIVATE],NOW)
        self.engine=m.Enricher(m.Ledger(self.ledger.path),self.engine.run,self.engine.request)
        await self.engine.tick([{**PRIVATE,'hex':'ddeeff'}],NOW+3601)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.ledger.counts(NOW),(1,1))

    async def test_long_lived_active_private_route_is_rechecked(self):
        live={**PRIVATE,'live':True,'observed':NOW}
        self.responses['flightaware']=(200,{'flights':[{**FLIGHT,'actual_on':None,'estimated_on':'2026-09-24T23:00:00Z'}]})
        await self.engine.tick([live],NOW)
        await self.engine.tick([{**live,'observed':NOW+1799}],NOW+1799)
        self.assertEqual(len(self.calls),1)
        await self.engine.tick([{**live,'observed':NOW+1801}],NOW+1801)
        self.assertEqual(len(self.calls),2)

    async def test_historical_miss_is_not_repeated_after_half_an_hour(self):
        self.responses['flightaware']=(200,{'flights':[]})
        await self.engine.tick([PRIVATE],NOW)
        await self.engine.tick([PRIVATE],NOW+3601)
        self.assertEqual(len(self.calls),1)

    async def test_exhausted_budget_and_one_private_per_tick(self):
        await self.engine.tick([PRIVATE,{**PRIVATE,'hex':'ddeeff'}],NOW)
        self.assertEqual(len(self.calls),1)
        for _ in range(24):self.ledger.reserve(NOW)
        await self.engine.tick([{**PRIVATE,'hex':'123456'}],NOW+30)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.engine.status['flightaware'],'budget_exhausted')


if __name__=='__main__':unittest.main()
