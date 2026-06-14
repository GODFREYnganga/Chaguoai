"""WhatsApp survey menus and translations."""

from __future__ import annotations

MAIN_MENU_OPTIONS = {
    "english": ["Method Match", "Ask Question", "Myths & Facts", "Report Side Effects", "Change Language"],
    "swahili": ["Njia Inayonifaa", "Uliza Swali", "Ukweli na Imani", "Ripoti Madhara", "Badilisha Lugha"],
    "french": ["Methode adaptee", "Poser Question", "Mythes et faits", "Signaler effets", "Changer de langue"],
    "portuguese": ["Metodo ideal", "Fazer Pergunta", "Mitos e fatos", "Relatar efeitos", "Mudar idioma"],
}

LANGUAGE_OPTIONS = ["English", "Kiswahili", "Francais", "Portugues"]
HEALTH_CONDITION_OPTIONS = ["High blood pressure", "Diabetes", "Heart disease", "Liver problem", "Cancer", "Migraines", "None"]
METHOD_AVOID_OPTIONS = ["Pills", "Injectables", "IUD", "Implants", "None"]
CHILDREN_COUNT_OPTIONS = ["0", "1", "2", "3 or more"]
YES_NO_OPTIONS = {
    "english": ["Yes", "No"],
    "swahili": ["Ndio", "Hapana"],
    "french": ["Oui", "Non"],
    "portuguese": ["Sim", "Não"],
}
PARTNER_SUPPORT_OPTIONS = {
    "english": ["Yes", "No", "No partner"],
    "swahili": ["Ndio", "Hapana", "Sina mpenzi"],
    "french": ["Oui", "Non", "Pas de partenaire"],
    "portuguese": ["Sim", "Não", "Sem parceiro"],
}
# ======================== TRANSLATIONS ========================
LANGUAGES = {
    "1": "english", "2": "swahili", "3": "french", "4": "portuguese"
}
LANGUAGE_ALIASES = {
    "english": "english",
    "kiswahili": "swahili",
    "swahili": "swahili",
    "francais": "french",
    "français": "french",
    "french": "french",
    "portugues": "portuguese",
    "português": "portuguese",
    "portuguese": "portuguese",
}

STRINGS = {
    "english": {
        "menu": "Welcome to ChaguoAI — your contraception decision support assistant.\n\nHow can I help today?",
        "ask_name": "Great! Let's start with your name.",
        "menu_btns": MAIN_MENU_OPTIONS["english"]
    },
    "swahili": {
        "menu": "Habari! Karibu ChaguoAI — msaidizi wako wa upangaji uzazi.\n\nNinawezaje kukusaidia leo?",
        "ask_name": "Safi sana! Hebu nianze kwa kufahamu jina lako kwanza.",
        "menu_btns": MAIN_MENU_OPTIONS["swahili"]
    },
    "french": {
        "menu": "Bienvenue sur ChaguoAI — votre assistant d'aide a la decision contraceptive.\n\nComment puis-je vous aider aujourd'hui ?",
        "ask_name": "Génial ! Commençons par votre nom.",
        "menu_btns": MAIN_MENU_OPTIONS["french"]
    },
    "portuguese": {
        "menu": "Bem-vindo ao ChaguoAI — seu assistente de apoio a decisao contraceptiva.\n\nComo posso ajudar hoje?",
        "ask_name": "Ótimo! Vamos começar com o seu nome.",
        "menu_btns": MAIN_MENU_OPTIONS["portuguese"]
    }
}
SURVEY_STRINGS = {
    "english": {
        "q1": "Q1/13: How old are you? (Reply with a number, e.g., 25).",
        "q2": "Q2/13: Your menstrual period or pregnancy status?",
        "q2_options": ["Within 4 weeks", "Not sure", "Currently pregnant"],
        "q3": "Q3/13: Do you have a baby under 6 months?",
        "q3_options": ["Yes", "No"],
        "q3a": "Q3a: Are you exclusively breastfeeding?",
        "q4": "Q4/13: How many living children do you have?",
        "q5": "Q5/13: Do you want more children?",
        "q5_options": ["Yes, in 2 years", "Yes, later", "No"],
        "q6": "Q6/13: Do you have any health conditions? (Select number(s) e.g. 1,2 or 7):\n1. High blood pressure\n2. Diabetes\n3. Heart disease\n4. Liver problem\n5. Cancer\n6. Migraines\n7. None",
        "q7": "Q7/13: Are you living with HIV?",
        "q7_options": ["Yes", "No", "Prefer not to say"],
        "q8": "Q8/13: Do you smoke?",
        "q9": "Q9/13: Have you used contraception before?",
        "q9a": "Q9a: Did you stop?",
        "q9a_options": ["Still using", "Stopped - side effects", "Stopped - other", "Switched"],
        "q10": "Q10/13: Does your partner support contraception?",
        "q11": "Q11/13: How difficult is it to visit a health facility?",
        "q11_options": ["Easy", "Sometimes hard", "Very hard"],
        "q12": "Q12/13: Do you also care about STI protection?",
        "q13": "Q13/13: Are there methods you prefer NOT to use?\n1. Pills\n2. Injectables\n3. IUD\n4. Implants\n5. None",
        "finished": "Thank you! I have collected your profile. Preparing your Method Match... Please wait."
    },
    "swahili": {
        "q1": "Q1/13: Una umri wa miaka mingapi? Jibu kwa nambari tu (Mfn. 25).",
        "q2": "Q2/13: Kipindi chako cha hedhi au hali ya ujauzito?",
        "q2_options": ["Ndani ya wiki 4", "Sina uhakika", "Nina mimba kwa sasa"],
        "q3": "Q3/13: Je, una mtoto chini ya miezi 6?",
        "q3_options": ["Ndio", "Hapana"],
        "q3a": "Q3a: Je, unanyonyesha maziwa ya mama pekee?",
        "q4": "Q4/13: Una watoto wangapi walio hai? Jibu kwa nambari (Mfn. 0 au 2).",
        "q5": "Q5/13: Je, unataka watoto zaidi?",
        "q5_options": ["Ndio, miaka 2", "Ndio, baadaye", "Hapana"],
        "q6": "Q6/13: Je, una hali yoyote ya kiafya? (Chagua nambari Mfn. 1,2 au 7):\n1. High blood pressure\n2. Diabetes\n3. Heart disease\n4. Liver problem\n5. Cancer\n6. Migraines\n7. None of the above",
        "q7": "Q7/13: Je, unaishi na virusi vya ukimwi (HIV)?",
        "q7_options": ["Ndio", "Hapana", "Sipendelei kusema"],
        "q8": "Q8/13: Je, unavuta sigara?",
        "q9": "Q9/13: Je, umewahi kutumia njia za kupanga uzazi hapo awali?",
        "q9a": "Q9a: Je, uliacha?",
        "q9a_options": ["Bado natumia", "Niliacha - madhara", "Niliacha - sababu zingine", "Nilibadilisha"],
        "q10": "Q10/13: Je, mpenzi wako anaunga mkono kupanga uzazi?",
        "q11": "Q11/13: Ni vigumu kiasi gani kutembelea kituo cha afya?",
        "q11_options": ["Rahisi", "Wakati mwingine ngumu", "Ngumu sana"],
        "q12": "Q12/13: Je, wajali pia kuhusu kujikinga na magonjwa ya zinaa (STI)?",
        "q13": "Q13/13: Kuna njia ambazo hupendi kutumia?\n1. Pills\n2. Injectables\n3. IUD\n4. Implants\n5. Hakuna / None",
        "finished": "Ahsante sana! Nimekusanya majibu yako yote. Naandaa mapendekezo yako ya Method Match... Tafadhali subiri kidogo."
    },
    "french": {
        "q1": "Q1/13: Quel âge avez-vous ? (Répondez avec un nombre, ex. 25).",
        "q2": "Q2/13: Votre période menstruelle ou état de grossesse ?",
        "q2_options": ["Moins de 4 semaines", "Pas sûr", "Actuellement enceinte"],
        "q3": "Q3/13: Avez-vous un bébé de moins de 6 mois ?",
        "q3_options": ["Oui", "Non"],
        "q3a": "Q3a: Allaiterez-vous exclusivement ?",
        "q4": "Q4/13: Combien d'enfants vivants avez-vous ?",
        "q5": "Q5/13: Voulez-vous plus d'enfants ?",
        "q5_options": ["Oui, dans 2 ans", "Oui, plus tard", "Non"],
        "q6": "Q6/13: Avez-vous des problèmes de santé ? (Sélectionnez le(s) numéro(s) ex. 1,2 ou 7):\n1. Hypertension\n2. Diabète\n3. Maladie cardiaque\n4. Problème de foie\n5. Cancer\n6. Migraines\n7. Aucun",
        "q7": "Q7/13: Vivez-vous avec le VIH ?",
        "q7_options": ["Oui", "Non", "Préfère ne pas dire"],
        "q8": "Q8/13: Fumez-vous ?",
        "q9": "Q9/13: Avez-vous déjà utilisé une contraception ?",
        "q9a": "Q9a: Avez-vous arrêté ?",
        "q9a_options": ["Toujours en cours", "Arrêté - effets secondaires", "Arrêté - autre", "Changé"],
        "q10": "Q10/13: Votre partenaire soutient-il la contraception ?",
        "q11": "Q11/13: Est-il difficile de visiter un centre de santé ?",
        "q11_options": ["Facile", "Parfois difficile", "Très difficile"],
        "q12": "Q12/13: Vous souciez-vous aussi de la protection contre les IST ?",
        "q13": "Q13/13: Y a-t-il des méthodes que vous préférez NE PAS utiliser ?\n1. Pilules\n2. Injectables\n3. DIU\n4. Implants\n5. Aucun",
        "finished": "Merci ! J'ai recueilli votre profil. Je prépare vos recommandations... Veuillez patienter."
    },
    "portuguese": {
        "q1": "Q1/13: Qual é a sua idade? (Responda com um número, ex. 25).",
        "q2": "Q2/13: Seu período menstrual ou estado de gravidez?",
        "q2_options": ["Menos de 4 semanas", "Não tenho certeza", "Atualmente grávida"],
        "q3": "Q3/13: Você tem um bebê com menos de 6 meses?",
        "q3_options": ["Sim", "Não"],
        "q3a": "Q3a: Você está amamentando exclusivamente?",
        "q4": "Q4/13: Quantos filhos vivos você tem?",
        "q5": "Q5/13: Você quer mais filhos?",
        "q5_options": ["Sim, em 2 anos", "Sim, mais tarde", "Não"],
        "q6": "Q6/13: Você tem alguma condição de saúde? (Selecione o(s) número(s) ex. 1,2 ou 7):\n1. Pressão alta\n2. Diabetes\n3. Doença cardíaca\n4. Problema de fígado\n5. Câncer\n6. Enxaquecas\n7. Nenhum",
        "q7": "Q7/13: Você vive com HIV?",
        "q7_options": ["Sim", "Não", "Prefiro não dizer"],
        "q8": "Q8/13: Você fuma?",
        "q9": "Q9/13: Você já usou contracepção antes?",
        "q9a": "Q9a: Você parou?",
        "q9a_options": ["Ainda usando", "Parou - efeitos colaterais", "Parou - outro", "Trocou"],
        "q10": "Q10/13: Seu parceiro apoia a contracepção?",
        "q11": "Q11/13: Quão difícil é visitar uma unidade de saúde?",
        "q11_options": ["Fácil", "Às vezes difícil", "Muito difícil"],
        "q12": "Q12/13: Você também se preocupa com a proteção contra IST?",
        "q13": "Q13/13: Existem métodos que você prefere NÃO usar?\n1. Pílulas\n2. Injetáveis\n3. DIU\n4. Implantes\n5. Nenhum",
        "finished": "Obrigado! Coletei seu perfil. Preparando suas recomendações... Aguarde."
    }
}

