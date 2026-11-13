"""On-demand replay visualization from one atomic processed-frame snapshot."""
import cv2
import numpy as np
from app.services.pose_preview import POSE_CONNECTIONS
from app.services.vault_wrist_interaction import reliable
from app.services.vault_region_profiles import REGIONS

REGION_COLORS = {
    'person_monitoring_roi': (55,210,70), 'vault_area_roi': (0,220,255),
    'vault_door_roi': (255,130,50), 'tray_area_roi': (220,100,190),
    'ornament_area_roi': (0,145,255),
}


def region_diagnostics(data):
    """Report actual frame-profile contents, independent of generic zone status."""
    configured = {row['id']: row for row in (data or {}).get('regions', [])}
    rows = []
    for identifier, name in REGIONS.items():
        zone = configured.get(identifier)
        polygon = zone.get('polygon', []) if zone else []
        valid = isinstance(polygon, list) and len(polygon) >= 3 and all(
            isinstance(p, (list,tuple)) and len(p) == 2 and all(isinstance(v,(int,float)) and np.isfinite(v) and 0 <= v <= 1 for v in p)
            for p in polygon)
        reason = 'Not configured in selected profile' if zone is None else 'Invalid polygon coordinates' if not valid else ''
        rows.append(dict(id=identifier, name=zone.get('name') or name if zone else name,
            loaded=bool(zone and valid), reason=reason, point_count=len(polygon) if isinstance(polygon,list) else 0,
            polygon=polygon if valid else None, enabled=zone.get('enabled',True) if zone else False))
    return rows


def render_pose_debug(jpeg, data, *, session_id, sequence, source_time):
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    height, width = image.shape[:2]
    scale = max(.5, width/1280)
    def point(p): return round(p['x']*width), round(p['y']*height)
    def text(label, xy, color=(255,255,255), size=.5):
        cv2.putText(image, label, xy, cv2.FONT_HERSHEY_SIMPLEX,size*scale,(0,0,0),max(2,round(4*scale)),cv2.LINE_AA)
        cv2.putText(image, label, xy, cv2.FONT_HERSHEY_SIMPLEX,size*scale,color,max(1,round(scale)),cv2.LINE_AA)
    text(f'POSE & ROI DEBUG | Frame {sequence} | {source_time:.3f}s | {session_id[:8]}', (round(16*scale), round(58*scale)), (255,230,120))
    if data:
        if data.get('pose_inference_ms') is not None:
            text(f"Poses: {len(data['poses'])} | inference {data['pose_inference_ms']:.1f} ms",(round(800*scale),round(58*scale)),size=.43)
        regions=region_diagnostics(data)
        polygons=[]
        for region in regions:
            if not region['loaded']:continue
            polygon=np.array([[round(x*width),round(y*height)] for x,y in region['polygon']],dtype=np.int32)
            color=REGION_COLORS[region['id']]
            tint=image.copy();cv2.fillPoly(tint,[polygon],color);cv2.addWeighted(tint,.08,image,.92,0,dst=image)
            polygons.append((region,polygon,color))
        # Draw all borders after fills so nested polygons keep their distinct colors.
        for region,polygon,color in polygons:
            cv2.polylines(image,[polygon],True,color,max(1,round(2*scale)))
            x,y=polygon[0];label_x=min(max(5,int(x)+5),max(5,width-round(230*scale)))
            label_y=min(height-10,max(18,int(y)+round(20*scale)))
            # Keep region names clear of the existing track status cards.
            if label_x < round(405*scale) and label_y < round((95+150*len(data.get('track_ids', [])))*scale):
                label_x=min(round(405*scale),max(5,width-round(230*scale)))
            text(region['name'],(label_x,label_y),color,size=.43)
        legend_x,legend_y=round(16*scale),max(0,height-round(160*scale))
        panel=image.copy();cv2.rectangle(panel,(legend_x-5,legend_y-20),(legend_x+round(480*scale),height-round(14*scale)),(18,18,30),-1);cv2.addWeighted(panel,.8,image,.2,0,dst=image)
        text('Regions - profile '+str(data.get('profile_id','unavailable')),(legend_x,legend_y),size=.46)
        for index,region in enumerate(regions):
            status=('LOADED' if region['enabled'] else 'LOADED (disabled)') if region['loaded'] else 'MISSING: '+region['reason']
            text(f"{region['name']}: {status} | {region['point_count']} points",
                (legend_x,legend_y+round((24+index*24)*scale)),REGION_COLORS[region['id']],size=.4)
        for number,(identifier,index) in enumerate(data['matches'].items()):
            pose=data['poses'][index]
            valid={k:point(p) for k,p in enumerate(pose) if reliable(p,data['confidence'])}
            for a,b in POSE_CONNECTIONS:
                if a in valid and b in valid:cv2.line(image,valid[a],valid[b],(255,210,80),max(1,round(2*scale)),cv2.LINE_AA)
            for p in valid.values():cv2.circle(image,p,max(2,round(3*scale)),(255,210,80),-1)
            wrists=[w for w in data['wrists'] if w['track_id']==identifier]
            y=round((95+number*150)*scale);x=round(16*scale)
            panel=image.copy();cv2.rectangle(panel,(x-5,y-20),(x+round(370*scale),y+round(112*scale)),(18,18,30),-1);cv2.addWeighted(panel,.75,image,.25,0,dst=image)
            text(f'Track {identifier}',(x,y))
            state=data.get('pose_states',{}).get(identifier,{})
            score=state.get('last_association_confidence')
            text(f"Pose: {state.get('pose_status','OBSERVED')} | score {score:.2f}" if score is not None else 'Pose: OBSERVED',(x,y+round(19*scale)),size=.4)
            for row,wrist in enumerate(wrists):
                label='INSIDE' if wrist['inside'] is True else 'OUTSIDE' if wrist['inside'] is False else 'UNRELIABLE'
                p=wrist.get('wrist') or {};v=p.get('visibility',0);presence=p.get('presence',0)
                text(f"{wrist['hand'].capitalize()}: {label} | v {v:.2f} p {presence:.2f}",(x,y+round((38+row*18)*scale)),size=.4)
            confirmed=data['states'][identifier]['confirmed']
            progress=max([w['progress_seconds'] for w in wrists if w['inside'] is True] or [0])
            status='CONFIRMED' if confirmed else f"CONFIRMING {progress:.1f} / {data['confirmation_seconds']:.1f} s" if progress>0 else 'WAITING'
            text('Last valid pose age: 0.00 s',(x,y+round(77*scale)),size=.4)
            text('Vault interaction: '+status,(x,y+round(99*scale)),(100,240,130) if confirmed else (255,255,255),size=.4)
        if not data['matches'] and not data.get('track_ids'):text('No reliable pose-to-track match for this frame',(20,round(100*scale)))
        unmatched=[identifier for identifier in data.get('track_ids',[]) if identifier not in data['matches']]
        for number,identifier in enumerate(unmatched,start=len(data['matches'])):
            y=round((95+number*150)*scale);x=round(16*scale)
            panel=image.copy();cv2.rectangle(panel,(x-5,y-20),(x+round(370*scale),y+round(112*scale)),(18,18,30),-1);cv2.addWeighted(panel,.75,image,.25,0,dst=image)
            state=data.get('pose_states',{}).get(identifier,{})
            text(f"Track {identifier} - {state.get('pose_status','UNMATCHED')}",(x,y))
            text(state.get('reason','NO_CURRENT_MATCH'),(x,y+round(20*scale)),(100,190,255),size=.37)
            text('Left / right wrist: UNAVAILABLE',(x,y+round(43*scale)),(180,180,180),size=.4)
            age=state.get('last_valid_pose_age');age_text=f'{age:.2f} s' if age is not None else 'never'
            text('Last valid pose age: '+age_text,(x,y+round(67*scale)),size=.4)
            status='CONFIRMED' if data['states'].get(identifier,{}).get('confirmed') else 'WAITING FOR POSE'
            text('Vault interaction: '+status,(x,y+round(97*scale)),size=.4)
        # Keep current wrist markers visible even when a diagnostic card overlaps.
        for wrist in data['wrists']:
            p=wrist['wrist'];inside=wrist['inside']
            if p and all(np.isfinite(p[k]) and 0 <= p[k] <= 1 for k in ('x','y')):
                xy=point(p);color=(40,220,50) if inside is True else (50,50,245) if inside is False else (170,170,170)
                cv2.circle(image,xy,max(4,round(7*scale)),color,-1)
                text(f"{wrist['track_id']} {wrist['hand'][0].upper()}",(xy[0]+10,xy[1]-8),color)
    else:
        text('Pose sample unavailable for this frame; no stale landmarks shown',(20,round(100*scale)))
    okay,encoded=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,80])
    if not okay:raise RuntimeError('Could not render debug preview')
    return encoded.tobytes()
