import logging
import os
import django
from liquid.models import YoutubedlVideo
import sys
from threading import Thread
import multiprocessing
import youtube_dl
from liquid_dl.settings import BASE_DIR
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'liquid_dl.settings')
django.setup()
STATIC_QUE = []
is_py2 = sys.version[0] == '2'

# Backwards Compatibility
if is_py2:
    from Queue import Queue as queue

    STATIC_QUE = queue()
else:
    import queue as queue

    STATIC_QUE = queue.Queue()

logger = logging.getLogger(__name__)


class MultiProcessorLogger(object):
    """
    Logger logs the information to the console that users may check logs
    """
    def __init__(self, video_id=None):
        self.video_id = video_id

    def debug(self, msg):
        print(msg)

    def warning(self, msg):
        pass

    def error(self, msg):
        print(msg)

    def progress(self, msg):
        print(msg)

    def my_hook(self, info):
        assert isinstance(info, dict)
        if info['status'] == 'downloading':
            # print(info)
            pass
        if info['status'] == 'finished':
            v, s = YoutubedlVideo.objects.update_or_create(url=self.video_id, defaults={
                "filename": info.get("filename"),
                "download_status": info.get("status", "finished"),
            })

            pass


class DownloadWorker(Thread):
    """
    Worker that uses youtube-dl pip package to download the video(s) at a given url
    """
    def __init__(self, download_worker_queue):
        Thread.__init__(self)
        self.queue = download_worker_queue

    def run(self):
        """
        Executes when put in the queue
        """
        directory, link, info_dict = self.queue.get()
        # print(link)
        assert isinstance(info_dict, dict)
        worker_logger = MultiProcessorLogger(video_id=link.get('id'), )
        ydl_opts = {
            'format': link.get('chosen_format'),
            'logger': MultiProcessorLogger(),
            'progress_hooks': [worker_logger.my_hook],
            'ignoreerrors': True
        }
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            ydl.download([link.get('id')])
            self.queue.task_done()


def youtube_dl_multiprocessor(download_dir, make_dir, info_dict, links=None):
    """
    Sets up multiple threads to download youtube videos in case of rate limiting or other factors that would limit 
    the main thread
    
    :param download_dir: the main folder where files will be downloaded or the parent folder of the directory we are 
                        going to create
    :param make_dir: determines if we must create a new directory
    :param info_dict: dictionary of values that determines the settings for liquid-dl (NOTICE: will be depreciated soon 
                      due to addition of settings.json file and use of sqlite)
    :param links: list of objects with id (for url) and and chosen_format
    :return:
    """
    if make_dir.get('make_dir'):
        # Check if Directory Exists or Make Directory
        if not os.path.exists(download_dir + '/' + make_dir.get('directory_name')):
            os.chdir(download_dir)
            os.mkdir(make_dir.get('directory_name'))
            download_dir = download_dir + '/' + make_dir.get('directory_name')
        else:
            os.chdir(download_dir + '/' + make_dir.get('directory_name'))
    os.chdir(download_dir)

    if links is None:
        links = []
    # Create a queue to communicate with the worker threads
    worker_queue = STATIC_QUE
    """
    We must fill the queue beforehand since the threads activate as soon as we insert our tuples and can give 
    file locking issues on Windows
    """
    for link in links:
        v, s = YoutubedlVideo.objects.update_or_create(url=link['id'], defaults={
            "download_status": "queued"
        })
        # print(link)
        logger.info('Queueing {0}'.format(link))
        # Put the tasks into the queue as a tuple
        worker_queue.put((download_dir, link, info_dict))
    # Create 8 worker threads
    for x in range(multiprocessing.cpu_count()):
        worker = DownloadWorker(worker_queue)
        # Setting daemon to True will let the main thread exit even though the workers are blocking
        worker.daemon = True
        worker.start()
    # Causes the main thread to wait for the queue to finish processing all the tasks
    worker_queue.join()
    os.chdir(BASE_DIR)
