"""RandomMadnessXer single-role generator.

Self-contained copy of the RMX generator from turbo_bot's
``turbo_bot/roles/role_definitions.py``. Produces a modbot-ready role dict
(base role id + randomized modifiers/powers) for a single faction.

Kept as a verbatim copy so future RMX tweaks in turbo_bot can be re-synced by
copying that logic here. Only depends on the standard library ``random``.
"""

import random

# Role id -> human-readable name (from turbo_bot role_definitions.py tables).
ROLE_NAMES = {
    # Town
    1: "Vanilla Town",
    3: "Town Alignment Cop",
    4: "Town Doctor",
    6: "Town Miller",
    8: "Town Role Cop",
    10: "Town Vigilante",
    12: "Town Roleblocker",
    14: "Town Jailkeeper",
    16: "Town Bodyguard",
    18: "Town Tracker",
    20: "Town Watcher",
    22: "Town Mason",
    23: "Town Lover",
    25: "Town Neighbor",
    27: "Town Innocent Child",
    28: "Town Full Cop",
    31: "Town Arsonist",
    34: "Town Firefighter",
    37: "Town Day Vigilante",
    39: "Town Jack of All Trades",
    41: "Town Universal Backup",
    43: "Town Alignment Oracle",
    44: "Town Role Oracle",
    46: "Town Parity Cop",
    48: "Town Bomber",
    50: "Town Poisoner",
    52: "Town Healer",
    54: "Town Motion Detector",
    56: "Town Voyeur",
    58: "Town Treestump",
    60: "Town Neapolitan",
    63: "Town Day Desperado",
    64: "Town Night Desperado",
    65: "Town Vanilla Cop",
    67: "Town Fruit Vendor",
    69: "Town Inventor",
    71: "Town Empowerer",
    73: "Town Redirector",
    75: "Town Power Role Killer",
    # Mafia
    2: "Mafia Goon",
    7: "Mafia Godfather",
    9: "Mafia Role Cop",
    11: "Mafia Vigilante",
    13: "Mafia Roleblocker",
    15: "Mafia Jailkeeper",
    17: "Mafia Bodyguard",
    19: "Mafia Tracker",
    21: "Mafia Watcher",
    24: "Mafia Lover",
    26: "Mafia Neighbor",
    29: "Mafia Full Cop",
    32: "Mafia Arsonist",
    35: "Mafia Firefighter",
    36: "Mafia Framer",
    38: "Mafia Day Vigilante",
    40: "Mafia Jack of All Trades",
    42: "Mafia Universal Backup",
    45: "Mafia Role Oracle",
    47: "Mafia Parity Cop",
    49: "Mafia Bomber",
    51: "Mafia Poisoner",
    53: "Mafia Healer",
    55: "Mafia Motion Detector",
    57: "Mafia Voyeur",
    59: "Mafia Treestump",
    61: "Mafia Neapolitan",
    62: "Mafia Alignment Cop",
    66: "Mafia Vanilla Cop",
    68: "Mafia Fruit Vendor",
    70: "Mafia Inventor",
    72: "Mafia Empowerer",
    74: "Mafia Redirector",
    76: "Mafia Power Role Killer",
}

# Base role ids per faction (see turbo_bot role tables).
possible_roles = {
    "Wolf": [
        2, 7, 9, 11, 13, 15, 17, 19, 21, 29,
        32, 35, 36, 38, 40, 42, 45, 47, 49, 51, 53, 55,
        57, 59, 61, 62, 66, 68, 70, 72, 74, 76
    ],
    "Village": [
        1, 3, 4, 6, 8, 10, 12, 14, 16, 18, 20,
        27, 28, 31, 34, 37, 39, 41, 43, 44, 46, 48, 50,
        52, 54, 56, 58, 60, 63, 64, 65, 67, 69, 71, 73, 75
    ],
}

possible_values = {
    "bpv_status": [1],
    "ninja": [1],
    "x_shot_limit": [2, 3],
    "strongman": [1],
    "godfather": [1],
    "backup": [1],
    "macho": [1],
    "lost": [1],
    "vengeful": [1],
    "flipless": [1],
    "vote_weight": [0, 1, 2, 3],
    "hide_vote_weight": [0, 1],
    "non_consecutive": [1],
    "self_targetable": [1],
    "treestump": [1, 2],
    "compulsive": [1],
    "loyal": [1],
    "disloyal": [1],
    "joat": [1],
    "inventor": [1],
    "disabled_in_endgame": [1],
    "janitor": [1, 2],
}

possible_vendor_items = {
    "vendor_items": [
        "benneh's threadpull", "boob1", "loopy69's autograph",
        "harold :3 adoption papers", "billager", "gori's hat",
        "ANNOUNCEMENT: INKAY IS GAY",
    ]
}

possible_utility_powers = {
    "alignment inspection": [1, 2],
    "fullcop": [1],
    "rolecop": [1, 2, 3],
    "neapolitan": [1, 2],
    "vanilla cop": [1, 2],
    "bodyguard": [1],
    "protection": [1, 2],
    "fire protection": [1, 2],
    "frame": [1],
    "jail": [1, 2],
    "roleblock": [1, 2],
    "redirect": [1, 2],
    "empower": [1, 2],
    "track": [1, 2],
    "watch": [1, 2],
    "motion detect": [1, 2],
    "voyeur": [1, 2],
    "heal": [1, 2],
}

possible_kill_powers = {
    "kill": [1, 2],
    "daykill": [1, 2],
    "desperado": [1],
    "day desperado": [1],
    "bomb": [1],
    "poison": [1, 2],
}


def get_static_values(faction):
    if faction == "Wolf":
        return {
            "faction": "Wolf",
            "alignment": "wolf",
            "faction_color": "#ff2244",
        }
    elif faction == "Village":
        return {
            "faction": "Village",
            "alignment": "village",
            "faction_color": "#339933",
        }
    else:
        raise ValueError("Invalid faction provided")


def randomize_night_restrictions():
    option = random.choice(["none", "even", "odd", "night_x"])

    if option == "none":
        return {"even_night": 0, "odd_night": 0, "night_x": 0}
    elif option == "even":
        return {"even_night": 1, "odd_night": 0, "night_x": 0}
    elif option == "odd":
        return {"even_night": 0, "odd_night": 1, "night_x": 0}
    else:  # option == "night_x"
        night_x = random.choice([1, 2, 3, "1+", "2+", 99])
        return {"even_night": 0, "odd_night": 0, "night_x": night_x}


def create_random_role(faction):
    role_id = random.choice(possible_roles[faction])
    static_values = get_static_values(faction)

    role = {
        "role": str(role_id),
        "role_name": ROLE_NAMES.get(role_id, "Unknown"),
        **static_values,
    }

    keys_to_modify = [key for key in possible_values.keys()]

    num_modifications = random.randint(1, 3)
    modifications = random.sample(keys_to_modify, min(num_modifications, len(keys_to_modify)))

    for key in modifications:
        role[key] = random.choice(possible_values[key])

    if role_id in [39, 40, 69, 70]:
        role["inventor"] = 0
        role["joat"] = 0
    if faction == "Wolf":
        if role.get("inventor") != 1 and role.get("joat") != 1 and role_id not in [39, 69, 40, 70]:
            for _ in range(2):
                if random.choice([True, False]):
                    if random.choice(["inventor", "joat"]) == "inventor":
                        role["inventor"] = 1
                    else:
                        role["joat"] = 1

    night_restrictions = randomize_night_restrictions()
    role.update(night_restrictions)

    role["powers"] = {}

    if role.get("joat") == 1 or role.get("inventor") == 1 or role_id in [39, 69, 40, 70]:
        num_utility_powers = random.randint(1, 3)
        utility_power_keys = list(possible_utility_powers.keys())
        selected_utilities = random.sample(utility_power_keys, min(num_utility_powers, len(utility_power_keys)))

        for power in selected_utilities:
            role["powers"][power] = random.choice(possible_utility_powers[power])

        num_kill_powers = 3 - num_utility_powers
        kill_power_keys = list(possible_kill_powers.keys())
        selected_kill_powers = random.sample(kill_power_keys, min(num_kill_powers, len(kill_power_keys)))

        for power in selected_kill_powers:
            role["powers"][power] = random.choice(possible_kill_powers[power])

    if role_id in [68, 67]:
        if "vendor_items" not in role:
            role["vendor_items"] = []
        num_vendor_items = random.randint(1, 3)
        vendor_items = possible_vendor_items["vendor_items"]
        selected_items = random.sample(vendor_items, min(num_vendor_items, len(vendor_items)))

        for power in selected_items:
            role["vendor_items"].append(power)

    return role
