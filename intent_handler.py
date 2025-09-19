from logger import logger
from sbert_intent import predict_intent_sbert  # already added earlier

def get_intent(tokens, raw_text):
    try:
        low = raw_text.lower()

        # 1) SBERT first — only accept if confident
        s_intent, score = predict_intent_sbert(raw_text)
        if s_intent:
            logger.debug(f"SBERT override → {s_intent} (score={score:.3f})")
            return s_intent

        # 2) Fallback to rules
        intents = {
            'plant_info': [
                'plant', 'plant details', 'generation plant', 'power plant', 'generator',
                'plf', 'paf', 'variable cost', 'aux consumption', 'max power', 'min power',
                'rated capacity', 'type', 'technical minimum', 'auxiliary consumption',
                'aux usage', 'auxiliary usage', 'var cost', 'plant load factor', 'plant availability factor'
            ],
            'banking': [  # <-- NEW
                'banking', 'banking unit', 'banked unit', 'banked units',
                'adjusted units', 'adjustment charges', 'banking cost', 'energy banked'
            ],
            'procurement': [
                'procurement', 'purchase', 'power purchase cost', 'ppc',
                'procurement price', 'last price', 'iex cost',
                'generated energy', 'energy generation', 'energy generated',
                'generated cost', 'generation cost', 'cost generated', 'cost generation'
            ],
            'mod': ['mod', 'moment of dispatch', 'dispatch price', 'mod price', 'mod rate', 'dispatch rate'],
            'iex': ['iex', 'exchange rate', 'market rate', 'market price', 'indian energy exchange'],
            'cost per block': ['cost per block', 'block cost', 'block price', 'rate per block'],
            'demand': ['demand', 'consumption', 'average demand', 'avg demand', 'load', 'forecast', 'prediction']
        }
        for intent, kws in intents.items():
            if any(k in low for k in kws):
                return intent

        return None
    except Exception as e:
        logger.error(f"Intent detection error: {e}", exc_info=True)
        return None
