from .acquisti_esterni import CONFIG as acquisti_esterni
from .assemblaggio import CONFIG as assemblaggio
from .lavorazioni_extra import CONFIG as lavorazioni_extra
from .macchine_utensili import CONFIG as macchine_utensili
from .molatura import CONFIG as molatura
from .piegatura import CONFIG as piegatura
from .sabbiatura import CONFIG as sabbiatura
from .saldatura import CONFIG as saldatura
from .taglio_lamiera import CONFIG as taglio_lamiera
from .taglio_profili import CONFIG as taglio_profili
from .trattamento_esterno import CONFIG as trattamento_esterno

phase_registry = {config.code: config for config in (
    taglio_lamiera, taglio_profili, piegatura, macchine_utensili, saldatura,
    sabbiatura, molatura, assemblaggio, lavorazioni_extra, acquisti_esterni,
    trattamento_esterno,
)}
