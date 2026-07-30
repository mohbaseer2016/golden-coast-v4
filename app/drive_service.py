import io
import os
from datetime import datetime
from pathlib import Path
from PIL import Image
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

class DriveStorage:
    def __init__(self):
        key_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        root_folder_id = os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_ID", "")
        if not key_path or not Path(key_path).exists() or not root_folder_id:
            raise RuntimeError("Google Drive غير مهيأ")
        credentials = service_account.Credentials.from_service_account_file(key_path, scopes=SCOPES)
        self.drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
        self.root_folder_id = root_folder_id

    def _folder(self, name: str, parent_id: str) -> str:
        safe = name.replace("'", "\'")
        q = f"name='{safe}' and mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false"
        found = self.drive.files().list(q=q, spaces="drive", fields="files(id,name)", pageSize=1).execute().get("files", [])
        if found:
            return found[0]["id"]
        return self.drive.files().create(body={"name":name,"mimeType":"application/vnd.google-apps.folder","parents":[parent_id]},fields="id").execute()["id"]

    def upload_image(self, invoice_no: str, kind: str, raw: bytes) -> str:
        now=datetime.now()
        year=self._folder(str(now.year),self.root_folder_id)
        month=self._folder(f"{now.month:02d}",year)
        inv=self._folder(invoice_no,month)
        image=Image.open(io.BytesIO(raw)).convert("RGB")
        image.thumbnail((1600,1600))
        out=io.BytesIO(); image.save(out,format="JPEG",quality=72,optimize=True)
        out.seek(0)
        media=MediaIoBaseUpload(out,mimetype="image/jpeg",resumable=False)
        created=self.drive.files().create(body={"name":f"{kind}_{now.strftime('%Y%m%d_%H%M%S')}.jpg","parents":[inv]},media_body=media,fields="id,webViewLink").execute()
        return created.get("webViewLink") or f"https://drive.google.com/file/d/{created['id']}/view"
