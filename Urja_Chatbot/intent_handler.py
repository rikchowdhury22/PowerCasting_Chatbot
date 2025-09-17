# intent_handler.py
from logger import logger

def get_intent(tokens, raw_text):
    try:
        low = raw_text.lower()

        intents = {
            'demand': [
                'demand', 'consumption', 'average demand', 'avg demand', 'load',
                'forecast', 'prediction', 'predicted', 'expected'
            ],

            'mod': [
                'mod', 'moment of dispatch', 'dispatch price', 'mod price', 'mod rate',
                'dispatch rate', 'moment of dispatch price', 'moment of dispatch rate'
            ],

            'iex': [
                'iex', 'exchange rate', 'exchange price', 'market rate', 'market price',
                'indian energy exchange'
            ],

            # ✅ Expanded to include gen-energy/banking/cost synonyms
            'procurement': [
                'procurement', 'purchase', 'power purchase cost', 'ppc',
                'procurement price', 'last price', 'iex cost',
                'generated energy', 'energy generation', 'energy generated',
                'banking', 'banking unit', 'banked', 'banked unit', 'banking contribution',
                'energy banked',
                'generated cost', 'generation cost', 'cost generated', 'cost generation'
            ],

            'cost per block': [
                'cost per block', 'block cost', 'block price', 'rate per block', 'cost rate', 'block rate'
            ],

            'plant_info': [
                'plant', 'plant details', 'generation plant', 'power plant', 'generator',
                'plf', 'paf', 'variable cost', 'aux consumption', 'max power', 'min power',
                'rated capacity', 'type', 'technical minimum', 'auxiliary consumption',
                'aux usage', 'auxiliary usage', 'var cost', 'plant load factor', 'plant availability factor'
            ]
        }

        for intent, kws in intents.items():
            if any(k in low for k in kws):
                return intent

        return None
    except Exception as e:
        logger.error(f"Intent detection error: {e}")
        return None
