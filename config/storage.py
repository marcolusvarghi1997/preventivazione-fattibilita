from whitenoise.storage import CompressedManifestStaticFilesStorage


class JazzminCompatibleManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    """
    Jazzmin costruisce dinamicamente gli URL dei temi partendo dalla directory
    ``vendor/bootswatch``. La directory non è una voce del manifest, mentre i
    singoli CSS lo sono: il fallback non-strict consente questo uso senza
    rinunciare agli hash per tutti i file presenti nel manifest.
    """

    manifest_strict = False
