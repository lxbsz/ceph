#define _FILE_OFFSET_BITS 64
#include <features.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <time.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <errno.h>
#include "include/cephfs/libcephfs.h"

int main(int argc, char *argv[]) {

        struct ceph_mount_info *cmount = NULL;
        int n = 64;
        bool parent = true;

        if (argc > 2)
                n = atoi(argv[2]);

        while (--n >= 0) {
                pid_t pid = fork();
                if (pid < 0) {
                        printf("fork fail %d\n", pid);
                        exit(-1);
                }
                if (pid == 0) {
                        parent = false;
                        break;
                }
        }
        if (parent) {
                pid_t pid;
                int status;
                while ((pid = wait(&status)) > 0);
                return 0;
        }

        ceph_create(&cmount, "admin");
        ceph_conf_read_file(cmount, "./ceph.conf");
        ceph_mount(cmount, NULL);

        ceph_chdir(cmount, argv[1]);

        char buf[4096];
        sprintf(buf, "dir%d", n);
        int ret = ceph_mkdir(cmount, buf, 0755);
        if (ret < 0 && ret != -EEXIST) {
                printf("ceph_mkdir fail %d\n", ret);
                return 0;
        }

        ceph_chdir(cmount, buf);

        /*
        struct ceph_dir_result *dirp;
        ret = ceph_opendir(cmount, ".", &dirp);
        if (ret < 0) {
                printf("ceph_opendir fail %d\n", ret);
                return 0;
        }

        while (ceph_readdir(cmount, dirp))
                ;

        ceph_closedir(cmount, dirp);
        */

        int count = 0;
        time_t start = time(NULL);
        for (int i = 0; i < 20000; ++i) {
                sprintf(buf, "file%d", i);
                int fd = ceph_open(cmount, buf, O_CREAT|O_RDONLY, 0644);
                if (fd < 0) {
                        printf("ceph_open fail %d\n", fd);
                        exit(-1);
                }
                /*
                ret = ceph_fchmod(cmount, fd, 0666);
                if (ret < 0) {
                        printf("ceph_fchmod fail %d\n", ret);
                        exit(-1);
                }
                */

                ceph_close(cmount, fd);
                count++;
                if (time(NULL) > start) {
                        printf("%d\n", count);
                        count = 0;
                        start = time(NULL);
                }
        }
        ceph_unmount(cmount);
        return 0;
}
