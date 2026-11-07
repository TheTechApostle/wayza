from sqlalchemy.orm import Session
from .models import Stop, Route, RouteStop, User
from .config import ADMIN_EMAIL, ADMIN_PASSWORD
from .security import hash_password

RAW = """Mile 12|6.6075|3.3979|Ikorodu Rd
Ketu|6.5968|3.3880|Ikorodu Rd
Ojota|6.5853|3.3790|Ikorodu Rd
Maryland|6.5667|3.3636|Ikorodu Rd
Anthony|6.5600|3.3667|Ikorodu Rd
Obanikoro|6.5528|3.3647|Ikorodu Rd
Palmgroove|6.5440|3.3615|Ikorodu Rd
Fadeyi|6.5360|3.3588|Ikorodu Rd
Jibowu|6.5176|3.3716|Yaba
Yaba|6.5095|3.3711|Yaba
Ebute Metta|6.4945|3.3787|Mainland
Oyingbo|6.4890|3.3870|Mainland
CMS|6.4500|3.3920|Lagos Island
Obalende|6.4503|3.4070|Lagos Island
Tafawa Balewa Square|6.4470|3.3980|Lagos Island
Ikoyi Falomo|6.4410|3.4280|Ikoyi
Victoria Island|6.4290|3.4200|VI
Lekki Toll Gate|6.4350|3.4540|Lekki
Lekki Phase 1|6.4480|3.4730|Lekki
Ajah|6.4680|3.5700|Lekki-Ajah
Ikorodu|6.6194|3.5105|Ikorodu
Oshodi|6.5568|3.3489|Oshodi
Ikeja Under Bridge|6.6018|3.3515|Ikeja
Allen Avenue|6.6014|3.3592|Ikeja
Alausa|6.6150|3.3560|Ikeja
Computer Village|6.5960|3.3430|Ikeja
Ojodu Berger|6.6350|3.3680|Ojodu
Ojodu|6.6560|3.3640|Ojodu
Agege|6.6190|3.3250|Agege
Iyana Ipaja|6.6120|3.2680|Ipaja
Ilupeju|6.5600|3.3550|Ilupeju
Gbagada|6.5540|3.3900|Gbagada
Oworonshoki|6.5450|3.3980|Oworonshoki
Mushin|6.5280|3.3550|Mushin
Ojuelegba|6.5086|3.3667|Surulere
Adeniran Ogunsanya|6.5000|3.3600|Surulere
Costain|6.4800|3.3650|Surulere
Apapa|6.4490|3.3590|Apapa
Mile 2|6.4650|3.3150|Badagry Rd
Festac 1st Gate|6.4650|3.2800|Festac
Ojo|6.4650|3.1800|Badagry Rd
Badagry|6.4150|2.8810|Badagry
Ikorodu Garage|6.6194|3.5105|Ikorodu
Ipakodo|6.617|3.506|Ikorodu
Agric Ikorodu|6.623|3.514|Ikorodu
Owode Onirin|6.59|3.392|Ikorodu Road
Ogudu|6.573|3.395|Ogudu
Ogba|6.635|3.339|Ogba
Iju Ishaga|6.651|3.318|Agege
Abule Egba|6.646|3.282|Agege
Egbeda|6.585|3.278|Alimosho
Idimu|6.545|3.268|Alimosho
Ikotun|6.547|3.263|Alimosho
Isolo|6.533|3.321|Isolo
Mafoluku|6.548|3.333|Oshodi
Airport Road|6.555|3.332|Oshodi
Cele|6.481|3.309|Isolo
Iyana Iba|6.47|3.203|Ojo
Alaba International|6.461|3.19|Ojo
Trade Fair Complex|6.452|3.27|Ojo
Agbara|6.449|3.075|Badagry
Sangotedo|6.469|3.602|Ajah
VGC|6.438|3.535|Lekki
Chevron|6.44|3.525|Lekki
Jakande|6.438|3.512|Lekki
Igbo Efon|6.438|3.5|Lekki
Lakowe|6.46|3.72|Ibeju-Lekki
Epe|6.584|3.983|Epe
Gbagada Phase 2|6.557|3.389|Gbagada
Bariga|6.538|3.389|Bariga
Shomolu|6.537|3.375|Shomolu
Onipanu|6.535|3.366|Shomolu
Iyana Oworo|6.545|3.405|Oworonshoki
Oshodi Terminal|6.556|3.3489|Oshodi
Mile 2 Under Bridge|6.465|3.315|Mile 2
Festac 2nd Gate|6.466|3.287|Festac
Amuwo Odofin|6.457|3.282|Amuwo
Volks|6.45|3.26|Ojo
Iyana School|6.473|3.227|Ojo
Jakande Estate Isolo|6.526|3.323|Isolo
Cele Express|6.479|3.315|Isolo
Ikeja Along|6.605|3.348|Ikeja
Alausa Secretariat|6.617|3.358|Ikeja
Ojodu Grammar School|6.638|3.365|Ojodu
Berger Bus Stop|6.635|3.368|Ojodu
Ikeja City Mall|6.619|3.353|Ikeja
Oniru|6.431|3.437|Victoria Island
Marina|6.451|3.397|Lagos Island
TBS|6.447|3.398|Lagos Island
Tin Can|6.436|3.343|Apapa
Liverpool|6.447|3.355|Apapa
Iyana Ipaja Roundabout|6.612|3.268|Ipaja"""

# Starter routes - approximate; admins can edit in the dashboard. Fares are ESTIMATES.
ROUTES = [
 ("IKR1", "Mile 12 - Yaba (Ikorodu Rd)", ["Mile 12","Ketu","Ojota","Maryland","Anthony","Obanikoro","Palmgroove","Fadeyi","Jibowu","Yaba"]),
 ("MNL1", "Yaba - CMS (Mainland to Island)", ["Yaba","Ebute Metta","Oyingbo","CMS"]),
 ("LEK1", "CMS - Ajah (Lekki Corridor)", ["CMS","Obalende","Ikoyi Falomo","Victoria Island","Lekki Toll Gate","Lekki Phase 1","Ajah"]),
 ("IKJ1", "Ojodu - Oshodi (Ikeja)", ["Ojodu","Ojodu Berger","Alausa","Allen Avenue","Ikeja Under Bridge","Computer Village","Oshodi"]),
 ("BAD1", "Badagry - Apapa (Badagry Expy)", ["Badagry","Ojo","Festac 1st Gate","Mile 2","Apapa"]),
 ('IKR2', 'Ikorodu – TBS', ['Ikorodu', 'Ikorodu Garage', 'Owode Onirin', 'Mile 12', 'Ketu', 'Ojota', 'Maryland', 'Jibowu', 'Yaba', 'CMS', 'TBS']),
 ('IKR3', 'Ikorodu – Ojota', ['Ikorodu', 'Ikorodu Garage', 'Agric Ikorodu', 'Ipakodo', 'Mile 12', 'Ketu', 'Ojota']),
 ('IKR4', 'Ikorodu – Gbagada', ['Ikorodu', 'Mile 12', 'Ketu', 'Ojota', 'Gbagada', 'Gbagada Phase 2']),
 ('IKR5', 'Ikorodu – Yaba', ['Ikorodu', 'Mile 12', 'Ketu', 'Ojota', 'Maryland', 'Fadeyi', 'Jibowu', 'Yaba']),
 ('IKE1', 'Ikeja – Oshodi', ['Ikeja Under Bridge', 'Ikeja Along', 'Computer Village', 'Mafoluku', 'Oshodi Terminal']),
 ('AGE1', 'Agege – Ikeja', ['Agege', 'Iju Ishaga', 'Ogba', 'Ikeja Under Bridge', 'Allen Avenue', 'Alausa']),
 ('AGE2', 'Abule Egba – Ikeja', ['Abule Egba', 'Iju Ishaga', 'Ogba', 'Ikeja Under Bridge', 'Alausa Secretariat']),
 ('IPA1', 'Iyana Ipaja – Oshodi', ['Iyana Ipaja', 'Egbeda', 'Idimu', 'Isolo', 'Mafoluku', 'Oshodi']),
 ('BER1', 'Ojodu Berger – CMS', ['Berger Bus Stop', 'Ojodu Berger', 'Alausa', 'Ikeja Under Bridge', 'Maryland', 'Ojota', 'Yaba', 'CMS']),
 ('OSH1', 'Oshodi – Victoria Island', ['Oshodi', 'Mushin', 'Ojuelegba', 'Yaba', 'CMS', 'Victoria Island']),
 ('OSH2', 'Oshodi – Mile 2', ['Oshodi', 'Mafoluku', 'Isolo', 'Cele', 'Mile 2']),
 ('SUR1', 'Ojuelegba – CMS', ['Ojuelegba', 'Yaba', 'Ebute Metta', 'Oyingbo', 'CMS']),
 ('SUR2', 'Surulere – Ikoyi', ['Adeniran Ogunsanya', 'Ojuelegba', 'Yaba', 'CMS', 'Obalende', 'Ikoyi Falomo']),
 ('AP1', 'Apapa – Oshodi', ['Apapa', 'Liverpool', 'Tin Can', 'Mile 2', 'Cele', 'Oshodi']),
 ('FES1', 'Festac – CMS', ['Festac 1st Gate', 'Festac 2nd Gate', 'Amuwo Odofin', 'Mile 2', 'Costain', 'CMS']),
 ('OJO1', 'Ojo – Iyana Ipaja', ['Ojo', 'Iyana Iba', 'Iyana School', 'Iyana Ipaja']),
 ('ISO1', 'Isolo – Oshodi', ['Jakande Estate Isolo', 'Isolo', 'Cele Express', 'Mafoluku', 'Oshodi Terminal']),
 ('KOS1', 'Ikotun – Ikeja', ['Ikotun', 'Idimu', 'Egbeda', 'Iyana Ipaja', 'Agege', 'Ikeja Under Bridge']),
 ('LEK2', 'Ajah – Epe', ['Ajah', 'Sangotedo', 'Lakowe', 'Epe']),
 ('LEK3', 'Ajah – Victoria Island', ['Ajah', 'Sangotedo', 'VGC', 'Chevron', 'Jakande', 'Igbo Efon', 'Lekki Phase 1', 'Victoria Island']),
 ('VI1', 'Victoria Island – Yaba', ['Victoria Island', 'Oniru', 'Ikoyi Falomo', 'Obalende', 'CMS', 'Yaba']),
 ('GBA1', 'Gbagada – Ojota', ['Gbagada', 'Gbagada Phase 2', 'Iyana Oworo', 'Ogudu', 'Ojota']),
 ('YAB1', 'Yaba – Ikorodu', ['Yaba', 'Jibowu', 'Fadeyi', 'Palmgroove', 'Maryland', 'Ojota', 'Ketu', 'Mile 12', 'Ikorodu']),
 ('OSH3', 'Oshodi – Ikeja', ['Oshodi', 'Mafoluku', 'Ikeja City Mall', 'Ikeja Under Bridge']),
 ('LEK4', 'Ajah – Lekki Phase 1', ['Ajah', 'Sangotedo', 'VGC', 'Chevron', 'Jakande', 'Igbo Efon', 'Lekki Phase 1']),
 ('BAD2', 'Badagry – Mile 2', ['Badagry', 'Agbara', 'Ojo', 'Iyana Iba', 'Alaba International', 'Trade Fair Complex', 'Festac 1st Gate', 'Mile 2']),
 ('M2C', 'Mile 2 – CMS', ['Mile 2', 'Amuwo Odofin', 'Costain', 'Apapa', 'CMS']),
 ('SHO1', 'Shomolu – Yaba', ['Shomolu', 'Onipanu', 'Fadeyi', 'Jibowu', 'Yaba']),
 ('BAR1', 'Bariga – CMS', ['Bariga', 'Gbagada', 'Ojota', 'Maryland', 'Yaba', 'CMS']),
 ('EGB1', 'Egbeda – Oshodi', ['Egbeda', 'Idimu', 'Isolo', 'Mafoluku', 'Oshodi Terminal']),
 ('EPE1', 'Epe – Ajah', ['Epe', 'Lakowe', 'Sangotedo', 'Ajah'])

]

def seed(db: Session):
    # Add missing starter stops and routes without deleting existing records.
    existing_stops = {x.name.lower(): x for x in db.query(Stop).all()}
    for line in RAW.split("\n"):
        if not line.strip():
            continue
        name, lat, lon, zone = line.split("|")
        if name.lower() not in existing_stops:
            stop = Stop(name=name, lat=float(lat), lon=float(lon), zone=zone)
            db.add(stop)
            existing_stops[name.lower()] = stop
    db.commit()

    existing_stops = {x.name.lower(): x for x in db.query(Stop).all()}
    existing_codes = {x.code for x in db.query(Route).all()}
    for code, name, names in ROUTES:
        if code in existing_codes:
            continue
        missing = [n for n in names if n.lower() not in existing_stops]
        if missing:
            continue
        route = Route(code=code, name=name)
        route.stops = [RouteStop(stop_id=existing_stops[n.lower()].id, seq=i) for i, n in enumerate(names)]
        db.add(route)
    db.commit()

    if ADMIN_EMAIL and ADMIN_PASSWORD and not db.query(User).filter_by(email=ADMIN_EMAIL.lower()).first():
        db.add(User(email=ADMIN_EMAIL.lower(), name="Admin", role="admin", password_hash=hash_password(ADMIN_PASSWORD)))
        db.commit()
